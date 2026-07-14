import logging
from typing import Optional

from ....auth.handler import AuthValidator
from ....core.config import AKConfig, ExecutionMode
from ...common import ThreadRunner
from .akoutputconsumer import ECSOutputConsumer


class ECSIOHandler:
    """
    ECS IO Handler — the queue-mode entrypoint. Starts two peer threads via ThreadRunner:
    the REST API and the output-queue consumer.

    Thread 1 (rest-api) runs the FastAPI/uvicorn app: ECSQueueRequestHandler in REST queue
    modes, or WebSocket (ASYNC/STREAM) frames via ECSWebSocketRequestHandler. Thread 2
    (output-queue-consumer) runs ECSOutputConsumer.run, writing to DB (REST) or pushing
    over WebSocket (ASYNC). WebSocket mode requires ``run(auth_validator=MyValidator())``.
    """

    _log = logging.getLogger("ak.ecs.iohandler")
    _config = AKConfig.get()

    @classmethod
    def run(cls, auth_validator: Optional[AuthValidator] = None) -> None:
        mode = cls._config.execution.mode
        cls._log.info(f"ECSIOHandler starting — mode={mode}")

        if mode in (ExecutionMode.ASYNC, ExecutionMode.STREAM):
            from .core.api.websocket_api import AWSWebsocketAPI

            # Auth is mandatory in WebSocket mode — fail fast rather than raise deep inside the thread.
            if auth_validator is None:
                raise ValueError(
                    "auth_validator is required for WebSocket (ASYNC/STREAM) mode. "
                    "Call ECSIOHandler.run(auth_validator=MyValidator())."
                )

            # Register the validator on AWSWebsocketAPI so its default handler picks it up.
            def run_api() -> None:
                AWSWebsocketAPI.set_auth_handler(auth_validator=auth_validator).run()
        else:
            from .core.api.rest_api import AWSRestAPI

            def run_api() -> None:
                AWSRestAPI.run()

        ThreadRunner.run(
            tasks=[
                ThreadRunner.Task(
                    execution_function=run_api,  # a callable so ThreadRunner runs it in the thread, not here
                    thread_name="rest-api",
                    stop_all_on_failure=True,
                    graceful=True,
                    awaited_on_shutdown=False,  # uvicorn.run() isn't wired to shutdown_event and only stops via OS signal, so it can't report completion.
                ),
                ThreadRunner.Task(execution_function=lambda: ECSOutputConsumer.run(), thread_name="output-queue-consumer", stop_all_on_failure=True),
            ],
            max_workers=2,
        )
