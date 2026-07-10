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
                                      frames are handled by ECSWebSocketRequestHandler.
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
        from ....api.http import RESTAPI

        mode = cls._config.execution.mode
        cls._log.info(f"ECSIOHandler starting — mode={mode}")

        if mode in (ExecutionMode.ASYNC, ExecutionMode.STREAM):
            from .ecs_ws_handler import ECSWebSocketRequestHandler

            request_handler = ECSWebSocketRequestHandler(auth_validator=auth_validator)
        else:
            from .ecs_queue_handler import ECSQueueRequestHandler

            request_handler = ECSQueueRequestHandler()

        ThreadRunner.run(
            tasks=[
                ThreadRunner.Task(
                    execution_function=lambda: RESTAPI.run(
                        handlers=[request_handler]
                    ),  # lambda needed here to wrap the function so that it turns into a callable, because otherwise the rest api will be run here itself
                    thread_name="rest-api",
                    stop_all_on_failure=True,
                    graceful=True,
                    awaited_on_shutdown=False,  # uvicorn.run() isn't wired to shutdown_event and only stops via OS signal, so it can't report completion.
                ),
                ThreadRunner.Task(execution_function=lambda: ECSOutputConsumer.run(), thread_name="output-queue-consumer", stop_all_on_failure=True),
            ],
            max_workers=2,
        )
