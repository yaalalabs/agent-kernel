"""The Lambda host for A2A and MCP (#932): ``LambdaProtocolHost``, its cold-start ``LambdaProtocolGuard`` and ``AppLifespan``.

The mode, transport and base-path checks of ``LambdaProtocolGuard``, and the class-level ``_loop`` and ``_run`` of
``LambdaProtocolHost``, mirror ``LambdaWebhookGuard`` and ``LambdaWebhookHost`` (``webhook_host.py``) on purpose. They stay
copies until the Lambda host refactor gives the two hosts a shared base class; moving onto it is then a small follow-up.
"""

import asyncio
import logging
import os
from collections.abc import Coroutine, Mapping
from typing import Any, ClassVar

from starlette.applications import Starlette
from starlette.exceptions import HTTPException

from .....api.http import RESTAPI
from .....core.config import AKConfig
from .....core.model import ExecutionMode
from .....core.util.factory import AKConfigError
from .....pipeline.io_handler import IOHandler
from .....pipeline.transport.base import QueueTransportFactory
from .event_translator import LambdaEventTranslator
from .protocol_paths import ProtocolPaths


class AppLifespan:
    """Holds an ASGI app's lifespan open for the life of the Lambda execution environment (#932).

    A server enters an app's lifespan once, when it starts, and leaves it when it stops. A Lambda has
    no server: each invocation is a plain call. FastMCP needs its lifespan, which opens a task group,
    and refuses every request until it has run. So the host enters the lifespan once per cold start
    and keeps it open across invocations.

    ``start`` creates one task on the running loop that enters ``app.router.lifespan_context`` and
    parks there. The loop has to outlive each invocation, so it is the host's long-lived loop, and
    the task is never closed: Lambda freezes the environment between calls, so shutdown needs no work.

    FastAPI and Starlette are imported at module scope, as in the rest of this package, so the
    class is reached only through the host's lazy export.
    """

    def __init__(self, app: Starlette):
        """:param app: The app whose lifespan to hold open; FastAPI is a Starlette app."""
        self._app = app
        self._task: asyncio.Task[None] | None = None
        self._failure: BaseException | None = None

    async def start(self) -> None:
        """Enter the lifespan and return once its startup has finished.

        :raises RuntimeError: If it was already started.
        :raises Exception: Whatever the app's startup raised, so a broken app fails the Lambda's
            init instead of its first request.
        """
        if self._task is not None:
            raise RuntimeError("The app's lifespan was already started")
        ready = asyncio.Event()
        self._task = asyncio.get_running_loop().create_task(self._hold(ready))
        await ready.wait()
        if self._failure is not None:
            raise self._failure

    async def _hold(self, ready: asyncio.Event) -> None:
        """Enter the lifespan, report startup through ``ready``, then park for good."""
        try:
            async with self._app.router.lifespan_context(self._app):
                ready.set()
                await asyncio.Event().wait()  # never set: the lifespan is not closed
        except BaseException as exc:
            if ready.is_set():
                raise  # torn down with the loop after start() returned: nothing to report
            self._failure = exc  # a failure in startup: start() re-raises it
            ready.set()
            if not isinstance(exc, Exception):
                raise  # a cancellation is not swallowed


class LambdaProtocolHost:
    """Serves A2A and MCP from the request Lambda by running the whole FastAPI app (#932).

    ``LambdaWebhookHost`` hands one endpoint a request. A2A and MCP are a FastAPI app (``RESTAPI.build_app``:
    the A2A routes per agent, the MCP mount), so this host builds that app once per cold start, keeps its
    lifespan open (FastMCP refuses every request until its lifespan has run), and answers each event by running
    the app on it. The executors the app mounts enqueue through ``RestHandler.request`` and wait for the reply in
    the response store, so the agent runs on the Agent Runner Lambda like every other surface.

    Build it at module scope, after the agents are registered (the app builds its cards and tools from the
    agent registry at cold start), and register its ``handle`` for every route in ``ProtocolPaths.ROUTES``
    (both are exported from ``agentkernel.aws``)::

        from agentkernel.aws import Lambda, LambdaProtocolHost, ProtocolPaths

        protocol = LambdaProtocolHost()
        for path, method in ProtocolPaths.ROUTES:
            Lambda.register(path, method=method)(protocol.handle)

    This module imports FastAPI and Starlette at module scope, so ``agentkernel.aws`` exports it lazily:
    ``from agentkernel.aws import Lambda`` stays fastapi-free.
    """

    _log = logging.getLogger("ak.aws.lambda.protocol")

    # One per execution environment, shared by every LambdaProtocolHost (LambdaWebhookHost keeps its own) and reused
    # across warm invocations, like uvicorn's single loop on the other surfaces. Never made the thread's
    # current loop, so run_async_sync elsewhere in the process sees what it saw before.
    _loop: ClassVar[asyncio.AbstractEventLoop | None] = None

    def __init__(self, translator: LambdaEventTranslator | None = None):
        """Check the deployment can serve A2A and MCP, build the app and open its lifespan, so a broken
        deployment fails its Lambda init loudly instead of failing calls later.

        :param translator: The event <-> Starlette translator; a default one when omitted.
        :raises AKConfigError: See LambdaProtocolGuard; or the app could not be built.
        :raises Exception: Whatever the app's startup raised.
        """
        LambdaProtocolGuard().check()
        self._translator = translator or LambdaEventTranslator()
        self._base_path = f"/{os.environ['API_BASE_PATH']}/{os.environ['API_VERSION']}"
        self._wait_budget_seconds = LambdaProtocolGuard.wait_budget_seconds()
        # An empty list, not None: None builds the direct chat routes, which run agents in this process.
        self._app = RESTAPI.build_app(handlers=[])
        self._lifespan = AppLifespan(self._app)
        self._run(self._lifespan.start())

    def handle(self, event: dict[str, Any], context: Any) -> dict[str, Any]:
        """Serve one A2A or MCP call (the router's ``(event, context)`` contract).

        :param event: The API Gateway REST (v1) proxy event.
        :param context: The Lambda context; its remaining time is checked against the wait budget.
        :return: The proxy response. A failure is a proxy response too, never an exception.
        """
        self._warn_if_the_wait_outlasts_the_invocation(context)
        response: dict[str, Any] = self._run(self._respond(event))
        return response

    async def _respond(self, event: Mapping[str, Any]) -> dict[str, Any]:
        """Run the app on the event, and turn any failure into the proxy response FastAPI would have sent.

        An unhandled exception would reach ``Lambda.handler``'s catch-all, which answers 500 with the exception text.
        """
        try:
            return await self._translator.call_app(self._app, event, self._app_path(event))
        except Exception as exc:  # HTTPException included: its status is the answer
            return await self._translator.error_to_proxy_response(exc)

    def _app_path(self, event: Mapping[str, Any]) -> str:
        """The path the app routes on: the event's path without ``/<API_BASE_PATH>/<API_VERSION>``.

        The exact path ``/mcp`` becomes ``/mcp/``: the app redirects the first to the second, and a redirect built
        from the stripped path points the client at a URL the gateway does not serve (spec Deviation 9).

        :raises HTTPException: 404 for a path that is neither A2A nor MCP.
        """
        path = event.get("path") or "/"
        app_path = path.removeprefix(self._base_path) if path == self._base_path or path.startswith(f"{self._base_path}/") else path
        if not ProtocolPaths.matches(app_path):
            raise HTTPException(404)
        return "/mcp/" if app_path == "/mcp" else app_path

    def _warn_if_the_wait_outlasts_the_invocation(self, context: Any) -> None:
        """Log a warning when waiting for the reply can outlast what the Lambda has left.

        The Lambda timeout is not in the environment, so the cold-start guard cannot check it (spec Deviation 7).
        """
        remaining_millis = getattr(context, "get_remaining_time_in_millis", None)
        if remaining_millis is None:
            return
        remaining_seconds = remaining_millis() / 1000
        if self._wait_budget_seconds > remaining_seconds:
            self._log.warning(
                f"The response store wait budget is {self._wait_budget_seconds:g}s ((retry_count - 1) x delay) but this invocation has "
                f"{remaining_seconds:g}s left: a slow agent run is cut off by the Lambda timeout. Raise the request-handler Lambda timeout "
                "or lower execution.response_store.retry_count x delay"
            )

    @classmethod
    def _run(cls, coro: Coroutine) -> Any:
        """Drive a coroutine on the execution environment's loop, replacing a closed one."""
        if cls._loop is None or cls._loop.is_closed():
            cls._loop = asyncio.new_event_loop()
        return cls._loop.run_until_complete(coro)


class LambdaProtocolGuard:
    """The cold-start checks LambdaProtocolHost runs (#932): fail at import, not on the first call."""

    REST_MODES = (ExecutionMode.REST_SYNC, ExecutionMode.REST_ASYNC)
    BASE_PATH_ENV = ("API_BASE_PATH", "API_VERSION", "AGENT_ENDPOINT")
    # API Gateway stops waiting for a REST integration at 29 seconds; raising it is a quota request.
    API_GATEWAY_TIMEOUT_SECONDS = 29

    def check(self) -> None:
        """Run the cold-start checks that are specific to Lambda; the topology checks are the ECS ones.

        Stateless MCP is checked whenever MCP is on, tool-only MCP included: it has sessions too.
        The queue checks (the sqs transport, the shared topology and the wait budget) apply only when A2A or agent MCP
        runs agents for the caller. An MCP server that serves only the application's own tools enqueues nothing and
        waits for nothing.

        :raises AKConfigError: The first check that fails, naming the setting and the fix.
        """
        self._check_mode()
        self._check_base_path_env()
        self._check_stateless_mcp()
        if RESTAPI.agent_protocol_surfaces():
            self._check_transport()
            self._check_shared_topology()
            self._check_wait_budget()

    @staticmethod
    def wait_budget_seconds() -> float:
        """How long ``RestHandler.request`` can wait for a reply: ``(retry_count - 1) x delay``.

        The first read of the response store is immediate, so one read fewer than ``retry_count`` is waited for.
        Zero without a ``response_store`` block: nothing waits for a reply then, because A2A and agent MCP, the
        only waiters, are refused without a shared store.
        """
        response_store = AKConfig.get().execution.response_store
        if response_store is None:
            return 0.0
        return max(response_store.retry_count - 1, 0) * response_store.delay

    def _check_mode(self) -> None:
        mode = AKConfig.get().execution.mode
        if mode == ExecutionMode.ASYNC:
            # An async deployment has no REST API and no response store; serving A2A and MCP there is tracked in #985.
            raise AKConfigError(
                "LambdaProtocolHost serves A2A and MCP in execution.mode rest_sync or rest_async only; got async. "
                "An async (WebSocket) deployment has no REST API for the /a2a and /mcp routes"
            )
        if mode not in self.REST_MODES:
            raise AKConfigError(
                f"LambdaProtocolHost serves A2A and MCP in execution.mode rest_sync or rest_async only; got {mode.value if mode else 'unset'}. "
                "Lambda routes the other modes' events to WSLambdaRouter"
            )

    def _check_transport(self) -> None:
        transport_type = QueueTransportFactory.resolve_type()
        if transport_type != "sqs":
            raise AKConfigError(
                f"LambdaProtocolHost needs the sqs queue transport, but execution.queues resolves to '{transport_type}': "
                "A2A and MCP enqueue every call and the serverless agent runner consumes the input queue through an SQS event source mapping, "
                "so with any other transport each call would time out. "
                "Set queue_mode = true in the ak-serverless Terraform module and execution.queues.type: sqs in config.yaml"
            )

    def _check_base_path_env(self) -> None:
        missing = [name for name in self.BASE_PATH_ENV if not os.getenv(name)]
        if missing:
            raise AKConfigError(
                f"LambdaProtocolHost needs {', '.join(missing)} in the environment: without them it cannot tell the A2A and MCP paths "
                "from the gateway's prefix. The ak-serverless Terraform module sets them on the request-handler Lambda"
            )

    def _check_shared_topology(self) -> None:
        """The checks and the no-agents warning ``IOHandler`` runs on ECS: a shared response store, since the Agent Runner
        Lambda writes the reply and this Lambda reads it."""
        config = AKConfig.get()
        IOHandler._validate_topology("sqs", config)
        IOHandler._warn_if_no_agents(config)

    def _check_stateless_mcp(self) -> None:
        """A call can land on any Lambda instance, so a stateful MCP session fails intermittently. ECS keeps one replica's session."""
        config = AKConfig.get()
        if config.mcp.enabled and not config.mcp.stateless_http:
            raise AKConfigError(
                "LambdaProtocolHost needs mcp.stateless_http: true: the next MCP call may reach another Lambda instance, which holds none of "
                "this one's sessions. Set it in config.yaml or AK_MCP__STATELESS_HTTP=true"
            )

    def _check_wait_budget(self) -> None:
        budget = self.wait_budget_seconds()
        if budget > self.API_GATEWAY_TIMEOUT_SECONDS:
            raise AKConfigError(
                f"execution.response_store waits up to {budget:g}s for a reply ((retry_count - 1) x delay), but API Gateway stops waiting "
                f"at {self.API_GATEWAY_TIMEOUT_SECONDS}s. Lower execution.response_store.retry_count or delay so the wait stays within "
                f"{self.API_GATEWAY_TIMEOUT_SECONDS}s"
            )
