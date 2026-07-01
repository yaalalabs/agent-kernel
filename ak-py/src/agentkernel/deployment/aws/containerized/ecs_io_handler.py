import logging

from ....api.http import RESTAPI
from ....core.config import AKConfig
from ...common import ThreadRunner
from .akoutputconsumer import ECSOutputConsumer


class ECSIOHandler:
    """
    ECS IO Handler — starts the REST API and the output-queue consumer as
    peer threads via ThreadRunner.

    Thread 1 (rest-api):              RESTAPI.run — FastAPI/uvicorn,
                                      ECSQueueRequestHandler registered.
    Thread 2 (output-queue-consumer): ECSOutputConsumer.run — polls the
                                      Output Queue, writes to DB / WebSocket.

    Usage::

        from agentkernel.deployment.aws.containerized import ECSIOHandler

        if __name__ == "__main__":
            ECSIOHandler.run()
    """

    _log = logging.getLogger("ak.ecs.iohandler")
    _config = AKConfig.get()

    @classmethod
    def run(cls) -> None:
        from .ecs_queue_handler import ECSQueueRequestHandler

        mode = cls._config.execution.mode
        cls._log.info(f"ECSIOHandler starting — mode={mode}")

        ThreadRunner.run(
            tasks=[
                ThreadRunner.Task(
                    execution_function=lambda: RESTAPI.run(
                        handlers=[ECSQueueRequestHandler()]
                    ),  # lambda needed here to wrap the function so that it turns into a callable, because otherwise the rest api will be run here itself
                    thread_name="rest-api",
                ),
                ThreadRunner.Task(
                    execution_function=lambda: ECSOutputConsumer.run(),
                    thread_name="output-queue-consumer",
                    stop_all_on_failure=True,
                ),
            ],
            max_workers=2
        )
