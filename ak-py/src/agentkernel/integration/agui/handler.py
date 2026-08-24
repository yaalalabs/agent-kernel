"""AG-UI surface: discovery, run routes, and the run lifecycle."""

import logging
from copy import deepcopy
from typing import Any, AsyncGenerator, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from ...api.handler import AuthorisedRESTRequestHandler
from ...auth.authoriser import Authoriser, AuthValidatorAuthoriser
from ...auth.handler import AuthValidator
from ...core.base import Agent
from ...core.chat_service import AgentHandler, ChatService
from ...core.config import AKConfig
from ...core.runtime import Runtime
from ...core.service import AgentService
from .mapping import AGUIMapper
from .run_input import AGUIRunInput
from .state import AGUI_STATE_KEY


class AGUIRequestHandler(AuthorisedRESTRequestHandler):
    """AG-UI routes: GET /agents, POST /{agent_name}, and POST / when `agui.default_agent` is set."""

    def __init__(self, authoriser: Optional[Authoriser] = None, auth_validator: Optional[AuthValidator] = None):
        """
        :param authoriser: Authoriser for the AG-UI routes.
        :param auth_validator: Wrapped as an Authoriser when `authoriser` is omitted.
        :raises ValueError: If the `agui` extra is missing, no authoriser or validator is given,
                            or `agui.default_agent` is not in `agui.agents`.
        """
        try:
            import ag_ui.core  # noqa: F401
        except ImportError as e:
            raise ValueError(
                "AG-UI support requires the 'ag-ui-protocol' package, which ships in Agent Kernel's "
                "'agui' extra. Install it with: pip install \"agentkernel[agui]\""
            ) from e

        if authoriser is None:
            if auth_validator is None:
                raise ValueError(
                    "AGUIRequestHandler requires an Authoriser or an AuthValidator. The AG-UI routes "
                    "run agents on a caller's behalf, so they are never served anonymously."
                )
            authoriser = AuthValidatorAuthoriser(auth_validator)

        super().__init__(authoriser)
        self._log = logging.getLogger("ak.integration.agui")
        self._chat_service = ChatService()

        config = AKConfig.get().agui
        if config.default_agent is not None and not self._is_exposed(config.default_agent):
            raise ValueError(
                f"agui.default_agent is '{config.default_agent}', which agui.agents does not expose. "
                f"Add it to agui.agents, or remove the default_agent setting."
            )

    @staticmethod
    def _is_exposed(agent_name: str) -> bool:
        """Whether `agui.agents` publishes this agent.

        :param agent_name: Agent name to test.
        :return: True when `agui.agents` is unset (every agent is reachable) or names this one.
        """
        exposed = AKConfig.get().agui.agents
        return exposed is None or agent_name in exposed

    def _warn_if_unreadable(self, agent: Agent, run_input: Any) -> None:
        """Warn about inbound fields no tool can read.

        `state`, `forwardedProps` and `context` are stored on the session regardless, but the tools
        that read them are attached only when their config block is enabled. Without this the field
        is accepted and silently unreachable, which looks like the model ignoring the data.

        :param agent: The agent this run resolved to.
        :param run_input: The parsed RunAgentInput.
        """
        from ...core.tool import SystemToolFactory

        agui = getattr(AKConfig.get(), "agui", None)

        def enabled(block_name: str) -> bool:
            """Whether a config block is enabled *and* in scope for this agent."""
            block = getattr(agui, block_name, None)
            return bool(block and block.enabled and SystemToolFactory._agent_allowed(block, agent.name))

        ignored = []
        if run_input.state is not None and not enabled("state"):
            ignored.append(("state", "agui.state"))
        if run_input.forwarded_props is not None and not enabled("client_context"):
            ignored.append(("forwardedProps", "agui.client_context"))
        if run_input.context and not enabled("client_context"):
            ignored.append(("context", "agui.client_context"))

        for field, flag in ignored:
            self._log.warning(
                f"Agent '{agent.name}' received '{field}' but {flag} is not enabled for it, so no tool can read it "
                f"and the value is ignored. Set {flag}.enabled to expose it."
            )

    def _resolve_agent(self, agent_name: str) -> Agent:
        """Resolve a path agent name to a streaming-capable, exposed agent.

        :param agent_name: Agent name taken from the route path.
        :return: The resolved Agent.
        :raises HTTPException: 404 when the agent is unknown *or* not exposed — deliberately
                               indistinguishable, so the surface never confirms that a hidden name
                               exists. 400 when the agent's runner cannot stream.
        """
        try:
            AgentService().ensure_agent_available(agent_name)
        except ValueError:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found")
        if not self._is_exposed(agent_name):
            raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found")
        agent = Runtime.current().agents()[agent_name]
        if not agent.runner.supports_streaming:
            raise HTTPException(
                status_code=400,
                detail=f"Agent '{agent_name}' runs on the '{agent.runner.name}' framework, whose Agent Kernel runner "
                f"does not implement streaming yet. AG-UI delivers a run as a stream of events, so the agent "
                f"becomes reachable here as soon as its runner declares supports_streaming — this is a pending "
                f"capability, not a permanent limit.",
            )
        return agent

    def get_router(self) -> APIRouter:
        """Build the AG-UI router under `agui.prefix`.

        The bare-prefix route is registered only when `agui.default_agent` is configured, so an
        unconfigured deployment returns 404 there rather than serving an arbitrary agent.

        :return: Router carrying the discovery and run routes.
        """
        config = AKConfig.get().agui
        router = APIRouter(prefix=config.prefix)

        @router.get("/agents")
        def list_agents(request: Request) -> dict:
            """List the names of agents reachable over AG-UI.

            Names only, deliberately: several adapters return the agent's *instructions* from
            get_description(), which would publish the system prompt to every authorised caller.

            :param request: Incoming request, for authorisation.
            :return: {"agents": [name, ...]}.
            """
            self._resolve_user(request)
            agents = Runtime.current().agents()
            return {"agents": [name for name, agent in agents.items() if agent.runner.supports_streaming and self._is_exposed(name)]}

        @router.post("/{agent_name}")
        async def run_agent(agent_name: str, request: Request) -> StreamingResponse:
            """Run the named agent.

            :param agent_name: Agent name from the path.
            :param request: Incoming request carrying the RunAgentInput body.
            :return: The AG-UI event stream.
            """
            return await self._run(agent_name, request)

        default_agent = config.default_agent
        if default_agent is not None:

            @router.post("")
            async def run_default_agent(request: Request) -> StreamingResponse:
                """Run `agui.default_agent`.

                :param request: Incoming request carrying the RunAgentInput body.
                :return: The AG-UI event stream.
                """
                return await self._run(default_agent, request)

        return router

    async def _run(self, agent_name: str, request: Request) -> StreamingResponse:
        """Validate a run request and hand back the event stream.

        Everything that can still be reported as an HTTP status happens here, before the response
        begins: authorisation, agent resolution, body parsing, and request mapping. `to_requests`
        runs before the session is written so a rejected part (audio, video) cannot leave state
        behind. Once `_events` starts yielding, the status is already sent and the only way to
        report a failure is a `RunError` event.

        :param agent_name: Agent to run.
        :param request: Incoming request carrying the RunAgentInput body.
        :return: A streaming response of encoded AG-UI events.
        :raises HTTPException: 400 for an unparsable or unusable body, 404/400 from agent
                               resolution, 500 when no session could be created.
        """
        from ag_ui.encoder import EventEncoder

        user_id = self._resolve_user(request)
        agent = self._resolve_agent(agent_name)

        try:
            body = await request.json()
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Request body is not valid JSON: {e}")
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="Request body must be a RunAgentInput object")

        run_input = AGUIRunInput.parse(body)
        requests = AGUIRunInput.to_requests(run_input)
        handler = self._chat_service.prepare_agent_handler(run_input.thread_id, agent_name)
        session = handler.service.session if handler.service is not None else None
        if session is None:
            self._log.error(
                f"Agent '{agent_name}' passed the AG-UI availability check but AgentService could not select it, "
                f"so no session was created. The two agent-resolution paths disagree."
            )
            raise HTTPException(status_code=500, detail=f"Agent '{agent_name}' could not be selected for this run")
        AGUIRunInput.set_agui_session_keys(session, run_input)
        self._warn_if_unreadable(agent, run_input)

        state_before = deepcopy(session.get_non_volatile_cache().get(AGUI_STATE_KEY))
        encoder = EventEncoder(accept=request.headers.get("accept"))  # type: ignore[arg-type]
        stream = self._events(encoder, handler, requests, run_input, state_before, user_id)
        return StreamingResponse(stream, media_type=encoder.get_content_type())

    async def _events(
        self,
        encoder: Any,
        handler: AgentHandler,
        requests: list,
        run_input: Any,
        state_before: Optional[dict],
        user_id: Optional[str],
    ) -> AsyncGenerator[str, None]:
        """Yield the run's encoded AG-UI events.

        `RunStarted` first, then the run's events, then exactly one of `RunFinished` or `RunError` —
        the protocol's bracket, which holds even when the run fails, because a client waits on that
        terminal event. Every failure is therefore reported as `RunError` rather than raised: the
        HTTP status is long gone by the time this generator runs.

        The `StateSnapshot` is emitted **only when the state actually changed**, which is why the
        caller captures `state_before` before the run: a turn that touches nothing re-syncs nothing.

        :param encoder: The SDK's EventEncoder, matched to the request's Accept header.
        :param handler: Prepared AgentHandler holding the selected agent and loaded session.
        :param requests: The mapped AgentRequest list to run.
        :param run_input: The parsed RunAgentInput, for thread and run ids.
        :param state_before: Deep copy of the AG-UI state taken before the run.
        :param user_id: Resolved caller, forwarded as the run's acting user.
        :return: An async generator of encoded SSE payloads.
        """
        from ag_ui.core import RunErrorEvent, RunFinishedEvent, RunStartedEvent, StateSnapshotEvent

        yield encoder.encode(RunStartedEvent(thread_id=run_input.thread_id, run_id=run_input.run_id, parent_run_id=run_input.parent_run_id))

        service = handler.service
        session = service.session if service is not None else None
        agent = service.agent if service is not None else None
        if session is None or agent is None:
            yield encoder.encode(RunErrorEvent(message="The agent session is no longer available for this run"))
            return

        agent_name = agent.name
        error: Optional[str] = None
        try:
            async for chunk in handler.run_stream_async(requests, acting_user_id=user_id):
                if chunk.error:
                    error = chunk.error
                    continue
                if chunk.event is None:
                    continue
                agui_event = AGUIMapper.to_agui(chunk.event)
                if agui_event is not None:
                    yield encoder.encode(agui_event)
        except Exception as e:
            self._log.exception(f"AG-UI run failed for agent '{agent_name}'")
            yield encoder.encode(RunErrorEvent(message=str(e)))
            return

        if error is not None:
            yield encoder.encode(RunErrorEvent(message=error))
            return

        state_after = session.get_non_volatile_cache().get(AGUI_STATE_KEY)
        if state_after != state_before:
            yield encoder.encode(StateSnapshotEvent(snapshot=state_after))

        yield encoder.encode(RunFinishedEvent(thread_id=run_input.thread_id, run_id=run_input.run_id))
