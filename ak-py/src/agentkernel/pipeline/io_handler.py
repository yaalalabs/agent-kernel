import logging
from typing import Optional

import uvicorn

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

    - ``in_memory``: single-process: all five pipeline components in one process. This is what
      a plain ``RESTAPI.run()`` boots on a laptop.
    - broker transports: two-process: this process serves the API and delivers responses;
      ``AgentRunner.run()`` is the second container.
    """

    _log = logging.getLogger("ak.pipeline.io_handler")

    @classmethod
    def run(cls, auth_validator: Optional[AuthValidator] = None) -> None:
        config = AKConfig.get()
        mode = config.execution.mode
        transport_type = QueueTransportFactory.resolve_type()
        cls._validate_topology(mode, transport_type, config)

        single_process = transport_type == "in_memory"
        cls._log.info(
            f"IOHandler starting: mode={mode}, transport={transport_type}, " f"topology={'single-process' if single_process else 'two-process'}"
        )

        from ..api.http import RESTAPI  # local import: RESTAPI.run() lazily imports this module

        # Serve through our own uvicorn.Server (not RESTAPI.run/uvicorn.run) so the main-thread
        # signal handlers below can stop it: uvicorn only installs its own handlers when it runs
        # on the main thread, and here it runs on the rest-api worker thread.
        host, port = config.api.host, config.api.port
        cls._log.info(f"Agent Kernel REST API listening on http://{host}:{port}")
        server = uvicorn.Server(uvicorn.Config(app=RESTAPI.build_app(handlers=[RequestHandler()]), host=host, port=port))
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
    def _validate_topology(cls, mode: Optional[ExecutionMode], transport_type: str, config) -> None:
        """Fail fast on unsupported/incoherent topology combinations (spec §9, §10)."""
        if mode == ExecutionMode.ASYNC:
            raise AKConfigError("ASYNC (WebSocket) mode over the pipeline ships in a later #495 iteration")
        if mode == ExecutionMode.STREAM and transport_type != "in_memory":
            raise AKConfigError("STREAM mode over a broker transport needs WebSocket delivery: ships in a later #495 iteration")
        if transport_type != "in_memory":
            response_store_config = config.execution.response_store
            if response_store_config is None or response_store_config.type in (None, "in_memory"):
                raise AKConfigError(
                    "multi-process queue modes need a shared response store (redis, valkey or dynamodb): "
                    "the in_memory store is single-process only"
                )
