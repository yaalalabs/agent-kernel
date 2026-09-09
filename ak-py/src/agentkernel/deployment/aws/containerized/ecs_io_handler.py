import logging
from typing import Optional

from ....api.handler import RESTRequestHandler
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

    Optional REST surfaces (the schedule and thread management routes, a Slack handler) are
    mounted by passing them as ``handlers``, the way the pipeline's ``IOHandler`` takes them.
    """

    _log = logging.getLogger("ak.ecs.iohandler")
    _config = AKConfig.get()

    @classmethod
    def run(cls, auth_validator: Optional[AuthValidator] = None, handlers: Optional[list[RESTRequestHandler]] = None) -> None:
        """Boot the REST/WebSocket API and the output-queue consumer as peer threads, and serve until shutdown.

        :param auth_validator: Authenticates the ``$connect`` handshake in WebSocket (ASYNC/STREAM)
            mode, where it is mandatory; unused in the REST queue modes.
        :param handlers: Optional REST handlers mounted alongside the API's own defaults, which are
            always served (the chat route is the queue producer, not a replaceable default).
            Mounting an optional surface is the application's job here, as it is on the pipeline's
            ``IOHandler``.
        :raises ValueError: If WebSocket mode is configured without an ``auth_validator``.
        """
        mode = cls._config.execution.mode
        cls._log.info(f"ECSIOHandler starting — mode={mode}")

        if mode in (ExecutionMode.ASYNC, ExecutionMode.STREAM):
            from .core.api.websocket_api import AWSWebsocketAPI

            # Auth is mandatory in WebSocket mode — fail fast rather than raise deep inside the thread.
            if auth_validator is None:
                raise ValueError(
                    "auth_validator is required for WebSocket (ASYNC/STREAM) mode. " "Call ECSIOHandler.run(auth_validator=MyValidator())."
                )

            # Register the validator on AWSWebsocketAPI so its default handler picks it up.
            def run_api() -> None:
                AWSWebsocketAPI.set_auth_handler(auth_validator=auth_validator).run(handlers=handlers)

        else:
            from .core.api.rest_api import AWSRestAPI

            def run_api() -> None:
                # Defaults first, then the application's: RESTAPI.run() replaces the defaults with
                # whatever it is handed, and the queue-producing chat route must survive.
                AWSRestAPI.run(handlers=[*AWSRestAPI.get_default_handlers(), *(handlers or [])])

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
