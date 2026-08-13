import logging
import signal
import threading
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
            ThreadRunner.Task(execution_function=ResponseHandler().start, thread_name="response-handler", stop_all_on_failure=True),
        ]
        if single_process:
            runner = StreamAgentRunner() if mode == ExecutionMode.STREAM else AgentRunner()
            tasks.append(ThreadRunner.Task(execution_function=runner.start, thread_name="agent-runner", stop_all_on_failure=True))

        ThreadRunner.run(tasks=tasks, max_workers=len(tasks))

    @classmethod
    def _install_signal_handlers(cls, server: uvicorn.Server) -> None:
        """Restore container-grade shutdown for the pipeline topology (spec §8).

        As a container's PID 1, a process with no SIGTERM handler never dies (the kernel drops
        default-disposition signals to PID 1), so `docker stop`/pod termination would hang until
        SIGKILL, and runtimes that never escalate would hang forever. The handler drains the
        pipeline gracefully: consumer loops observe `ThreadRunner.shutdown_event`, uvicorn stops
        via `should_exit`, and the ThreadRunner drain exits with code 0 (an orchestrated stop is
        not a failure).
        """
        if threading.current_thread() is not threading.main_thread():
            cls._log.warning("IOHandler is not running on the main thread; skipping signal handlers")
            return

        def _handle_shutdown_signal(signum: int, frame) -> None:
            cls._log.info(f"Received signal {signum}: shutting down the pipeline gracefully")
            ThreadRunner.shutdown_exit_code = 0
            ThreadRunner.shutdown_event.set()
            server.should_exit = True

        for shutdown_signal in (signal.SIGTERM, signal.SIGINT):
            signal.signal(shutdown_signal, _handle_shutdown_signal)

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
