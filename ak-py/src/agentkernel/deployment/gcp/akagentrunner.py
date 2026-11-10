"""The agent runner of queue mode on Cloud Run (spec #886 §6).

The input queue is a Pub/Sub push subscription that calls this service once per request, and the
response status acknowledges it. Cloud Run scales the service on those calls, down to zero, so the
runner needs no autoscaler of its own.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from fastapi import Body, FastAPI, Response

if TYPE_CHECKING:  # pragma: no cover: typing only, so importing this module stays light
    from ...pipeline.transport.pubsub import PubSubPushReceiver


class CloudRunAgentRunner:
    """Serves the input queue's Pub/Sub push deliveries and runs the agents.

    The counterpart of ``CloudRun.run()``, which starts the edge: deploy the same application as a
    second Cloud Run service whose entry point calls ``CloudRunAgentRunner.run()``. Each push
    request runs one message exactly as ``AgentRunner`` would have run it from a pull: same
    processing, same receive counting, same permanent-failure path and dead-letter copy.

    Usage::

        from agentkernel.gcp import CloudRunAgentRunner

        def runner() -> None:
            CloudRunAgentRunner.run()

    Pub/Sub waits at most 600 seconds for a push response. A run that takes longer is redelivered
    while it is still going and runs a second time: the accepted cost of push on Cloud Run.
    """

    PUSH_PATH = "/pubsub/push"

    _log = logging.getLogger("ak.gcp.agent_runner")

    @classmethod
    def run(cls) -> None:
        """Serve push deliveries on ``api.host``:``api.port`` until the process is stopped.

        :raises AKConfigError: If the transport is not ``pubsub``, for ``async`` or ``realtime``
            mode, or for ``in_memory`` sessions, before anything starts.
        """
        import uvicorn

        from ...core.config import AKConfig
        from ...core.util.factory import AKConfigError
        from ...pipeline.agent_runner import AgentRunner, StreamAgentRunner
        from ...pipeline.envelope import QueueName
        from ...pipeline.transport.base import QueueTransportFactory
        from .akcloudrun import CloudRun

        transport_type = QueueTransportFactory.resolve_type()
        if transport_type != "pubsub":
            raise AKConfigError(
                f"CloudRunAgentRunner serves Pub/Sub push deliveries, but execution.queues.type is '{transport_type}': "
                "set it to pubsub, or run AgentRunner.run() for a pull consumer"
            )
        CloudRun.reject_undeliverable_modes()

        config = AKConfig.get()
        if config.session.type == "in_memory":
            raise AKConfigError(
                "CloudRunAgentRunner needs a shared session store: Cloud Run runs several runner instances and scales to "
                "zero, so in_memory sessions would split across instances and be lost. Set session.type (redis, valkey or firestore)"
            )
        transport = QueueTransportFactory.create()
        # The same choice AgentRunner.run() makes; realtime is refused above.
        runner = StreamAgentRunner(transport=transport) if config.execution.is_delta else AgentRunner(transport=transport)
        receiver = transport.create_push_receiver(
            QueueName.INPUT,
            process=runner.process,
            on_permanent_failure=runner.on_permanent_failure,
            max_receive_count=config.execution.queues.input.max_receive_count,
        )

        host, port = config.api.host, config.api.port
        cls._log.info(f"Agent Kernel agent runner serving Pub/Sub push deliveries on http://{host}:{port}{cls.PUSH_PATH}")
        uvicorn.run(app=cls.build_app(receiver), host=host, port=port, reload=False)

    @classmethod
    def build_app(cls, receiver: PubSubPushReceiver) -> FastAPI:
        """The runner's web app: the push route plus a health route for Cloud Run's startup probe.

        The push route is a plain function, so FastAPI runs each delivery on its worker-thread pool
        and the agent run never blocks the event loop.
        """
        app = FastAPI(title="Agent Kernel agent runner")

        @app.get("/health")
        def health() -> dict[str, str]:
            return {"status": "ok"}

        @app.post(cls.PUSH_PATH)
        def push(body: dict[str, Any] = Body(...)) -> Response:
            try:
                status = receiver.handle(body)
            except Exception:
                # The bookkeeping store is unreachable, for example: a nack, so Pub/Sub redelivers.
                cls._log.exception("Failed to handle a push delivery: answering with a nack for redelivery")
                status = 500
            return Response(status_code=status)

        return app
