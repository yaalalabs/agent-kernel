import logging

from ....api.handler import RESTRequestHandler
from ....api.http import RESTAPI
from ....core.config import AKConfig
from ....core.util.factory import AKConfigError
from ....identity.provider.factory import IdentityProviderFactory
from ...common import ThreadRunner
from .akoutputconsumer import ECSOutputConsumer


class ECSIOHandler:
    """
    ECS IO Handler: the queue-mode entrypoint. Starts two peer threads via ThreadRunner:
    the REST API and the output-queue consumer.

    Thread 1 (rest-api) runs the FastAPI/uvicorn app: ECSQueueRequestHandler in REST queue
    modes, or WebSocket (async) frames via ECSWebSocketRequestHandler. Thread 2
    (output-queue-consumer) runs ECSOutputConsumer.run, writing to DB (REST) or pushing
    over WebSocket (async). Callers authenticate through the configured identity provider
    (the ``identity`` block): every REST route carries the identity dependency, and the
    WebSocket ``$connect`` handshake validates its ``token`` through the same provider, so
    WebSocket mode requires the block.

    Optional REST surfaces (the schedule and thread management routes, a Slack handler) are
    mounted by passing them as ``handlers``, the way the pipeline's ``IOHandler`` takes them.
    """

    _log = logging.getLogger("ak.ecs.iohandler")
    _config = AKConfig.get()

    @classmethod
    def run(cls, handlers: list[RESTRequestHandler] | None = None) -> None:
        """Boot the REST/WebSocket API and the output-queue consumer as peer threads, and serve until shutdown.

        :param handlers: Optional REST handlers mounted alongside the API's own defaults, which are
            always served (the chat route is the queue producer, not a replaceable default).
            Mounting an optional surface is the application's job here, as it is on the pipeline's
            ``IOHandler``.
        :raises AKConfigError: If A2A or agent-exposing MCP is enabled: their executors need the queue
            pipeline's agent runner, which ECS does not support for them yet (#780).
        :raises AKConfigError: If WebSocket (async) mode is configured without an ``identity`` block:
            ``$connect`` authenticates through the provider and keys the connection by its subject.
        :raises AKConfigError: For rest_sync + delta (SSE), which the ECS REST container does not serve.
        """
        # Before any thread starts: inside the rest-api thread the same refusal would come too late.
        RESTAPI.reject_unqueued_protocols()
        execution = cls._config.execution
        mode = execution.mode
        if execution.is_sse:
            # ECSQueueRequestHandler is the plain RestHandler: it waits for one stored record.
            raise AKConfigError(
                "execution.mode rest_sync with message_type delta (SSE) is not served by the ECS deployment: its REST "
                "container (ECSQueueRequestHandler) has no SSE route. Use execution.mode async with message_type delta (WebSocket)"
            )
        cls._log.info(f"ECSIOHandler starting: mode={mode}, message_type={execution.resolved_message_type}")

        if execution.is_websocket:
            from .core.api.websocket_api import AWSWebsocketAPI

            # Fail fast here rather than deep inside the rest-api thread.
            if IdentityProviderFactory.get() is None:
                raise AKConfigError(
                    "WebSocket (async) mode authenticates the $connect handshake through the identity provider: add an identity block"
                )

            def run_api() -> None:
                AWSWebsocketAPI.run(handlers=handlers)

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
