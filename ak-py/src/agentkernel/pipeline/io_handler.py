import logging
from typing import Optional

import uvicorn

from ..api.handler import RESTRequestHandler
from ..auth.handler import AuthValidator
from ..core.config import AKConfig
from ..core.model import ExecutionMode
from ..core.util.factory import AKConfigError
from .agent_runner import AgentRunner, StreamAgentRunner
from .request_handler import RequestHandler
from .response_handler import ResponseHandler
from .thread_runner import ThreadRunner
from .transport.base import QueueTransportFactory


class IOHandler:
    """Pipeline IO entry point (spec #495 §8): REST API + Response Handler as peer threads,
    plus the Agent Runner in-process when the transport is in_memory.

    Topology by transport:

    - ``in_memory``: single-process: all five pipeline components in one process (this is what
      a plain ``RESTAPI.run()`` boots on a laptop), co-hosting the WebSocket gateway handlers
      in ASYNC/STREAM when a validator is passed, since a separate gateway process cannot share
      an in-process queue.
    - broker transports: this process serves the plain-REST API and delivers responses;
      ``AgentRunner.run()`` and, in WS modes, ``WebSocketGateway.run()`` are their own
      containers.
    """

    _log = logging.getLogger("ak.pipeline.io_handler")

    @classmethod
    def run(cls, auth_validator: Optional[AuthValidator] = None, handlers: Optional[list[RESTRequestHandler]] = None) -> None:
        """Boot the pipeline topology this configuration implies and serve until shutdown.

        :param auth_validator: Only meaningful on the ``in_memory`` transport, where it co-hosts
            the WebSocket gateway (the ``/ws`` route plus the push endpoint) in ASYNC/STREAM
            modes; mandatory there for ASYNC. Broker topologies authenticate at their standalone
            gateway instead (``WebSocketGateway.run(auth_validator=...)``). Claims must include
            a ``userId``.
        :param handlers: Optional REST handlers mounted alongside the pipeline's own chat route,
            which is always served (it is the queue producer, not a replaceable default).
            Mounting an optional surface is the application's job here, as it is for the Slack
            and thread handlers.
        :raises AKConfigError: If the topology is unusable.
        """
        config = AKConfig.get()
        mode = config.execution.mode
        transport_type = QueueTransportFactory.resolve_type()
        cls._validate_topology(mode, transport_type, config, auth_validator)

        single_process = transport_type == "in_memory"
        if not single_process and mode in (ExecutionMode.ASYNC, ExecutionMode.STREAM):
            from .ws.push import default_connection_store

            # Raises on session backends without a connection store; a process-local store
            # cannot tell this process where another pod's sockets are.
            if not default_connection_store().shared:
                raise AKConfigError(
                    "WebSocket delivery over a broker transport needs a shared connection store: " "configure session.type redis, valkey or dynamodb"
                )
        ws_cohosted = single_process and auth_validator is not None and mode in (ExecutionMode.ASYNC, ExecutionMode.STREAM)
        cls._log.info(
            f"IOHandler starting: mode={mode}, transport={transport_type}, "
            f"topology={'single-process' if single_process else 'multi-process'}, websocket={'co-hosted' if ws_cohosted else 'off'}"
        )

        from ..api.http import RESTAPI  # local import: RESTAPI.run() lazily imports this module

        handlers = [RequestHandler(), *(handlers or [])]
        if ws_cohosted:
            from .ws.endpoint import PushEndpointHandler
            from .ws.handler import PipelineWebSocketHandler

            handlers += [PipelineWebSocketHandler(auth_validator=auth_validator), PushEndpointHandler()]
        elif auth_validator is not None:
            cls._log.warning(
                f"auth_validator ignored: WebSocket handling is co-hosted here only on the in_memory transport "
                f"in ASYNC/STREAM (mode={mode}, transport={transport_type}); on broker transports start "
                "WebSocketGateway.run(auth_validator=...) as its own process"
            )

        # Serve through our own uvicorn.Server (not RESTAPI.run/uvicorn.run) so the main-thread
        # signal handlers below can stop it: uvicorn only installs its own handlers when it runs
        # on the main thread, and here it runs on the rest-api worker thread.
        host, port = config.api.host, config.api.port
        cls._log.info(f"Agent Kernel REST API listening on http://{host}:{port}")
        server = uvicorn.Server(uvicorn.Config(app=RESTAPI.build_app(handlers=handlers), host=host, port=port))
        cls._install_signal_handlers(server)

        tasks = [
            ThreadRunner.Task(
                execution_function=server.run,
                thread_name="rest-api",
                stop_all_on_failure=True,
                graceful=True,
                awaited_on_shutdown=False,  # exits via server.should_exit on signals, not shutdown_event (see ECSIOHandler)
            ),
            ThreadRunner.Task(
                # exit_on_shutdown=False: the nested loop returns after draining (finishing its
                # in-flight work); only this outer ThreadRunner.run ends the process, once every
                # pipeline loop has reported in.
                execution_function=lambda: ResponseHandler().start(exit_on_shutdown=False),
                thread_name="response-handler",
                stop_all_on_failure=True,
            ),
        ]
        if single_process:
            runner = StreamAgentRunner() if mode == ExecutionMode.STREAM else AgentRunner()
            tasks.append(
                ThreadRunner.Task(
                    execution_function=lambda: runner.start(exit_on_shutdown=False), thread_name="agent-runner", stop_all_on_failure=True
                )
            )

        ThreadRunner.run(tasks=tasks, max_workers=len(tasks))

    @classmethod
    def _install_signal_handlers(cls, server: uvicorn.Server) -> None:
        """Restore container-grade shutdown for the pipeline topology (spec §8).

        Delegates to the shared ThreadRunner handler (which covers the PID-1 rationale and the
        exit-code-0 drain), adding the IOHandler-specific step: stopping the embedded uvicorn
        server via ``should_exit``, since uvicorn installs its own handlers only when it runs on
        the main thread and here it runs on the rest-api worker thread.
        """

        def _stop_uvicorn() -> None:
            server.should_exit = True

        ThreadRunner.install_shutdown_signal_handlers(cls._log, on_shutdown_signal=_stop_uvicorn)

    @classmethod
    def _validate_topology(cls, mode: Optional[ExecutionMode], transport_type: str, config, auth_validator: Optional[AuthValidator] = None) -> None:
        """Fail fast on unsupported/incoherent topology combinations (spec §9, §10)."""
        if mode == ExecutionMode.ASYNC and transport_type == "in_memory" and auth_validator is None:
            raise AKConfigError(
                "ASYNC (WebSocket) mode on the in_memory transport co-hosts the gateway here: call "
                "IOHandler.run(auth_validator=...) with a validator whose claims include a 'userId'"
            )
        if mode in (ExecutionMode.ASYNC, ExecutionMode.STREAM) and transport_type != "in_memory":
            # This process's Response Handler pushes replies to the gateway pods: it needs the
            # shared secret (and, checked at delivery setup, the shared connection store).
            if not config.websocket_api.push_auth_token:
                raise AKConfigError(
                    "WebSocket delivery over a broker transport needs websocket_api.push_auth_token: "
                    "the Response Handler authenticates its pushes to the gateway pods with it"
                )
        if transport_type != "in_memory" and mode not in (ExecutionMode.ASYNC, ExecutionMode.STREAM):
            # REST modes only (spec §10): the enqueueing or polling pod and the consuming pod
            # can differ, so replies must travel through a shared store. WebSocket modes never
            # touch the response store: replies push to the gateway pods instead.
            response_store_config = config.execution.response_store
            if response_store_config is None or response_store_config.type in (None, "in_memory"):
                raise AKConfigError(
                    "multi-process REST queue modes need a shared response store (redis, valkey or dynamodb): "
                    "the in_memory store is single-process only"
                )
