"""
The AG-UI surface: discovery, the run routes, and the run lifecycle.

AG-UI is a streaming protocol, so this handler owns three things no other AK surface does — a run
identity (`RunStarted` … `RunFinished` / `RunError`), an event vocabulary (see `mapping.py`), and a
shared state object it syncs back with `StateSnapshot`.

**Authorization narrows the inherited contract rather than reimplementing it.**
`AuthorisedRESTRequestHandler` owns the Bearer parsing and the 401 mapping, and returns `None` when
no authoriser is configured — which leaves routes open. That is right for thread reads and wrong
here, so the constructor refuses to build without one. The open branch is then unreachable.

**The handler drives `Runtime.stream` directly rather than `ChatService.execute_stream`, and the
reason is not stylistic.** `execute_stream` loads the session itself, by id. AG-UI has to write three
things onto the session *before* the run — `state`, `forwardedProps` and `context` — and read the
state back *after* it, so it needs the same session object throughout. Under any persistent session
store `load()` returns a fresh object per call, and `store()` deliberately excludes the volatile
cache (`Session.get_all(volatile=False)`), so props written on a handler-loaded copy could never
reach a run that loaded its own: `get_forwarded_props()` would return `{}` on every request, silently,
everywhere except the in-memory store. Owning the load is what makes the client-context tools work at
all.

Everything that can fail is resolved before the `StreamingResponse` is constructed — identity, the
agent, the body, the session — so a bad request is an HTTP status, not a well-formed stream whose
first event is an error.
"""

import logging
from copy import deepcopy
from typing import Any, AsyncGenerator, List, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from ...api.handler import AuthorisedRESTRequestHandler
from ...auth.authoriser import Authoriser, AuthValidatorAuthoriser
from ...auth.handler import AuthValidator
from ...core.base import Agent, Session
from ...core.config import AKConfig
from ...core.model import AgentRequest
from ...core.runtime import Runtime
from .mapping import to_agui
from .run_input import apply_to_session, parse_run_input, to_requests


class AGUIRequestHandler(AuthorisedRESTRequestHandler):
    """
    API router exposing Agent Kernel agents over the AG-UI protocol.
    Endpoints (under `agui.prefix`, default `/agui`):
    - GET /agui/agents: list the agents reachable over AG-UI
    - POST /agui/{agent_name}: run an agent, streaming AG-UI events
    - POST /agui: run `agui.default_agent`, registered only when one is configured

    Every route requires a Bearer token the configured Authoriser resolves to a user; unlike the
    thread routes, there is no open mode. An agent that `agui.agents` does not expose is treated
    exactly as an unknown agent, so the surface never confirms that a name exists.
    """

    def __init__(self, authoriser: Optional[Authoriser] = None, auth_validator: Optional[AuthValidator] = None):
        """
        Initializes an AGUIRequestHandler instance.
        :param authoriser: User-supplied Authoriser protecting the AG-UI routes.
        :param auth_validator: An existing AuthValidator to use instead, adapted to an Authoriser.
                               Passed explicitly because RESTAPI.add_auth_handlers keeps no
                               retrievable registry of the validators it turns into dependencies.
        :raises ValueError: If the `agui` extra is not installed, if neither an authoriser nor an
                            auth validator is given, or if `agui.default_agent` names an agent that
                            `agui.agents` does not expose.
        """
        try:
            import ag_ui.core  # noqa: F401 — presence check; the modules that use it import lazily
        except ImportError as e:
            raise ValueError(
                "AG-UI support requires the 'ag-ui-protocol' package, which ships in Agent Kernel's "
                "'agui' extra. Install it with: pip install 'ak[agui]'"
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

        config = AKConfig.get().agui
        if config.default_agent is not None and not self._is_exposed(config.default_agent):
            raise ValueError(
                f"agui.default_agent is '{config.default_agent}', which agui.agents does not expose. "
                f"Add it to agui.agents, or remove the default_agent setting."
            )

    @staticmethod
    def _is_exposed(agent_name: str) -> bool:
        """Whether `agui.agents` exposes this name. An absent list exposes every agent."""
        exposed = AKConfig.get().agui.agents
        return exposed is None or agent_name in exposed

    def _resolve_agent(self, agent_name: str) -> Agent:
        """Resolve a path agent name to a streaming-capable, exposed agent.

        :param agent_name: The agent name taken from the route path.
        :return: The resolved Agent.
        :raises HTTPException: 404 when the agent is unknown *or* not exposed — deliberately
                              indistinguishable, so the surface does not confirm a name exists.
                              400 when the agent's runner cannot stream.
        """
        agent = Runtime.current().agents().get(agent_name)
        if agent is None or not self._is_exposed(agent_name):
            raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found")
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
        """
        Returns the APIRouter instance carrying the AG-UI routes.
        """
        config = AKConfig.get().agui
        router = APIRouter(prefix=config.prefix)

        @router.get("/agents")
        def list_agents(request: Request) -> dict:
            # Names only, matching AgentRESTRequestHandler.list_agents. Deliberately not
            # agent.get_description(): several adapters return the agent's instructions from it (e.g.
            # framework/openai/openai.py:270), which would publish the system prompt — including the
            # injected system-tool guidance — to every authorised caller.
            self._resolve_user(request)
            agents = Runtime.current().agents()
            return {"agents": [name for name, agent in agents.items() if agent.runner.supports_streaming and self._is_exposed(name)]}

        @router.post("/{agent_name}")
        async def run_agent(agent_name: str, request: Request) -> StreamingResponse:
            return await self._run(agent_name, request)

        default_agent = config.default_agent
        if default_agent is not None:

            @router.post("")
            async def run_default_agent(request: Request) -> StreamingResponse:
                return await self._run(default_agent, request)

        return router

    async def _run(self, agent_name: str, request: Request) -> StreamingResponse:
        """Validate a run request and return the AG-UI event stream for it.

        Every rejection happens here rather than inside the generator, so the client sees an HTTP
        status for a bad request instead of a 200 whose first event is an error.

        :param agent_name: The agent to run.
        :param request: The incoming FastAPI request.
        :return: A StreamingResponse of encoded AG-UI events.
        :raises HTTPException: 401, 404 or 400 — see _resolve_agent and run_input.parse_run_input.
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

        run_input = parse_run_input(body)
        session = Runtime.current().sessions().load(run_input.thread_id)
        apply_to_session(session, run_input)
        requests = to_requests(run_input)

        # Deep copy, not a reference: get_agui_state() hands back the live dict, so keeping the
        # reference would compare the object with itself after a tool mutated it and report
        # "unchanged" on every run. Taken after the inbound state is applied, so state the client
        # just sent is not echoed straight back at it.
        state_before = deepcopy(session.get_agui_state())

        # EventEncoder's own signature is `accept: str = None`, so an absent header is passed
        # through as-is rather than coerced to "" — the value it would negotiate from, if it ever did.
        encoder = EventEncoder(accept=request.headers.get("accept"))  # type: ignore[arg-type]
        stream = self._events(encoder, agent, session, requests, run_input, state_before, user_id)
        return StreamingResponse(stream, media_type=encoder.get_content_type())

    async def _events(
        self,
        encoder: Any,
        agent: Agent,
        session: Session,
        requests: List[AgentRequest],
        run_input: Any,
        state_before: Optional[dict],
        user_id: Optional[str],
    ) -> AsyncGenerator[str, None]:
        """Emit one AG-UI run: RunStarted, the translated events, and exactly one terminal event.

        A client disconnect deliberately emits nothing: the generator is closed and there is nobody
        left to write to, so no terminal event is attempted — which is why nothing is yielded from a
        `finally` block here.
        """
        from ag_ui.core import RunErrorEvent, RunFinishedEvent, RunStartedEvent, StateSnapshotEvent

        yield encoder.encode(RunStartedEvent(thread_id=run_input.thread_id, run_id=run_input.run_id, parent_run_id=run_input.parent_run_id))

        error: Optional[str] = None
        try:
            async for chunk in Runtime.current().stream(agent, session, requests, acting_user_id=user_id):
                if chunk.error:
                    # An error chunk is always terminal (a halted pre-hook, or a failure the
                    # runtime caught), so record it and let the loop end on its own rather than
                    # closing the runtime's generator early.
                    error = chunk.error
                    continue
                if chunk.event is None:
                    continue
                agui_event = to_agui(chunk.event)
                if agui_event is not None:
                    yield encoder.encode(agui_event)
        except Exception as e:
            self._log.exception(f"AG-UI run failed for agent '{agent.name}'")
            yield encoder.encode(RunErrorEvent(message=str(e)))
            return

        if error is not None:
            yield encoder.encode(RunErrorEvent(message=error))
            return

        # Only on the success path. Runtime.stream persists the session after the loop drains, so on
        # an error path the state change was never stored — announcing it would leave the client
        # holding state the server discarded.
        state_after = session.get_agui_state()
        if state_after != state_before:
            yield encoder.encode(StateSnapshotEvent(snapshot=state_after))

        yield encoder.encode(RunFinishedEvent(thread_id=run_input.thread_id, run_id=run_input.run_id))
