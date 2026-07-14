import logging
from typing import Optional

from ....auth.handler import AuthValidator
from ....core.config import AKConfig, ExecutionMode
from ...common import ThreadRunner
from .akoutputconsumer import ECSOutputConsumer


class ECSIOHandler:
    """
    ECS IO Handler — the QUEUE-MODE entrypoint. Starts the REST API and the
    output-queue consumer as peer threads via ThreadRunner.

    Only used in queue mode. Non-queue deployments run RESTAPI.run directly (see the
    aws-containerized examples), so both threads here always apply.

    Thread 1 (rest-api):              RESTAPI.run — FastAPI/uvicorn. In REST queue
                                      modes ECSQueueRequestHandler is registered; in
                                      WebSocket (ASYNC/STREAM) mode the proxied WS
                                      frames are handled by ECSWebSocketRequestHandler
                                      (chat + any routes registered via
                                      AWSWebsocketAPI.register — not by subclassing).
    Thread 2 (output-queue-consumer): ECSOutputConsumer.run — polls the Output Queue;
                                      writes to DB (REST) or pushes over WebSocket (ASYNC).

    Usage::

        from agentkernel.deployment.aws.containerized import ECSIOHandler

        if __name__ == "__main__":
            ECSIOHandler.run()  # WebSocket mode: ECSIOHandler.run(auth_validator=MyValidator())
    """

    _log = logging.getLogger("ak.ecs.iohandler")
    _config = AKConfig.get()

    @classmethod
    def run(cls, auth_validator: Optional[AuthValidator] = None) -> None:
        mode = cls._config.execution.mode
        cls._log.info(f"ECSIOHandler starting — mode={mode}")

        if mode in (ExecutionMode.ASYNC, ExecutionMode.STREAM):
            from .core.api.websocket_api import AWSWebsocketAPI

            # Authentication is mandatory for WebSocket mode — fail fast with a clear message
            # instead of letting the handler constructor raise deep inside the thread.
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
                    execution_function=run_api,  # passed as a callable so ThreadRunner invokes it in the thread, rather than running the API here
                    thread_name="rest-api",
                    stop_all_on_failure=True,
                    graceful=True,
                    awaited_on_shutdown=False,  # uvicorn.run() isn't wired to shutdown_event and only stops via OS signal, so it can't report completion.
                ),
                ThreadRunner.Task(execution_function=lambda: ECSOutputConsumer.run(), thread_name="output-queue-consumer", stop_all_on_failure=True),
            ],
            max_workers=2,
        )
