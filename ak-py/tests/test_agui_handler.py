"""
Tests for the AG-UI surface (spec #523 §9, `integration/agui/handler.py`).

Four of these guard failures with no other symptom:

- **The StateSnapshot deep copy.** The nv_cache entry for AG-UI state is the live dict, so a handler holding
  the reference compares the object with itself and reports "unchanged" on every run. The surface
  still works; it just never syncs state back. `test_a_tool_updating_state_emits_a_snapshot` is what
  fails when that regresses.
- **The unbalanced TextMessageStart.** A run that fails mid-message must end with `RunError` and no
  synthesised `TextMessageEnd` — a handler that balanced the boundaries would assert a completion
  that did not happen, and would pass every other test here.
- **The session the run executes in.** The handler must stream through the same session object
  `ChatService.prepare_agent_handler` loaded, after writing `forwardedProps` onto it. `test_client_context_reaches_a_tool_with_a_copying_store` uses a
  store whose `load()` returns a fresh copy — the behaviour of every persistent store — so it fails
  if the handler ever lets the run load its own.
- **The 404 for an unexposed agent.** It must be indistinguishable from an unknown one, or the
  surface confirms which agent names exist.
"""

import json
import logging
from contextlib import contextmanager
from copy import deepcopy
from typing import Any, Optional

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentkernel.auth import Authoriser
from agentkernel.auth.handler import AuthValidator, ValidationResult
from agentkernel.core.base import Agent, Runner, Session
from agentkernel.core.config import _AGUIConfig, _GuardrailConfig
from agentkernel.core.event import MessageEnd, MessageStart, TextDelta, ToolCallStart
from agentkernel.core.hooks import PreHook
from agentkernel.core.model import AgentReplyText, AgentRequestText
from agentkernel.core.runtime import Runtime
from agentkernel.core.session.in_memory import InMemorySessionStore
from agentkernel.core.tool import ToolContext
from agentkernel.integration.agui import AGUIRequestHandler
from agentkernel.integration.agui.state import AGUI_STATE_KEY, AGUIState

GOOD_TOKEN = "good-token"
AUTH = {"Authorization": f"Bearer {GOOD_TOKEN}"}


class StaticAuthoriser(Authoriser):
    """Resolves exactly one token, so 401 has a live path in every test below."""

    def authorise(self, token: str) -> Optional[str]:
        return "u1" if token == GOOD_TOKEN else None


class ScriptedRunner(Runner):
    """Yields a fixed script. An Exception in the script is raised at that point in the stream, and
    a callable is invoked (that is how a mid-stream tool call is simulated)."""

    def __init__(self, script, name="scripted", streaming=True):
        super().__init__(name)
        self._script = script
        self._streaming = streaming

    @property
    def supports_streaming(self) -> bool:
        return self._streaming

    async def run(self, agent, session, requests):
        return AgentReplyText(response="unused")

    async def stream(self, agent, session, requests):
        for item in self._script:
            if isinstance(item, Exception):
                raise item
            if callable(item):
                with ToolContext(runtime=Runtime.current(), agent=agent, session=session, requests=requests) as context:
                    context.set()
                    try:
                        item()
                    finally:
                        context.reset()
                continue
            yield item


class ScriptedAgent(Agent):

    def __init__(self, name="assistant", script=None, streaming=True, runner_name="scripted"):
        super().__init__(name, ScriptedRunner(script if script is not None else [], runner_name, streaming))

    def get_a2a_card(self):
        return None

    def get_description(self):
        return f"{self.name} description"

    def override_system_prompt(self, prompt):
        pass

    def attach_tool(self, tool):
        pass


class HaltingPreHook(PreHook):
    """Stands in for a guardrail rejection: halts the run by returning a reply."""

    def name(self):
        return "halting-hook"

    async def on_run(self, session, agent, requests):
        return AgentReplyText(response="blocked by policy")


class CopyingSessionStore(InMemorySessionStore):
    """Returns a deep copy from load(), the way every persistent store does. In-memory is the only
    store that hands back the live object, so testing against it alone hides a whole class of bug."""

    def load(self, session_id: str, strict: bool = False) -> Session:
        return deepcopy(super().load(session_id, strict))


def _install_cfg(monkeypatch, agui_cfg):
    """Point AKConfig.get() at a stub carrying every section this path reads."""

    class _Cfg:
        agui = agui_cfg
        multimodal = None
        sandbox = None
        guardrail = _GuardrailConfig()

        class session:
            type = "in_memory"

    monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: _Cfg))


@contextmanager
def serving(monkeypatch, agents, agui_cfg=None, authoriser=None, store=None):
    """Mount the AG-UI router over a runtime holding the given agents."""
    _install_cfg(monkeypatch, agui_cfg if agui_cfg is not None else _AGUIConfig())
    Runtime._system_pre_hooks = []
    Runtime._system_post_hooks = []
    runtime = Runtime(store if store is not None else InMemorySessionStore())
    for agent in agents:
        runtime.register(agent)
    try:
        with runtime:
            app = FastAPI()
            app.include_router(AGUIRequestHandler(authoriser=authoriser or StaticAuthoriser()).get_router())
            yield TestClient(app), runtime
    finally:
        Runtime._system_pre_hooks = None
        Runtime._system_post_hooks = None


def body(**overrides):
    payload = {
        "threadId": "session-1",
        "runId": "run-1",
        "state": None,
        "messages": [{"id": "m1", "role": "user", "content": "hello"}],
        "tools": [],
        "context": [],
        "forwardedProps": None,
    }
    payload.update(overrides)
    return payload


def events(response) -> list[dict]:
    """Parse an SSE body into the AG-UI event dicts it carries."""
    return [json.loads(line[len("data: ") :]) for line in response.text.splitlines() if line.startswith("data: ")]


def types_of(response) -> list[str]:
    return [event["type"] for event in events(response)]


TEXT_SCRIPT = [MessageStart(message_id="m1"), TextDelta(message_id="m1", content="hi"), MessageEnd(message_id="m1")]


class TestRouteShape:

    def test_the_routes_are_registered_under_the_configured_prefix(self, monkeypatch):
        with serving(monkeypatch, [ScriptedAgent()], _AGUIConfig(prefix="/ui")) as (client, _):
            assert client.get("/ui/agents", headers=AUTH).status_code == 200
            assert client.post("/ui/assistant", headers=AUTH, json=body()).status_code == 200

    def test_the_bare_route_is_absent_without_a_default_agent(self, monkeypatch):
        with serving(monkeypatch, [ScriptedAgent()]) as (client, _):
            assert client.post("/agui", headers=AUTH, json=body()).status_code == 404

    def test_the_bare_route_serves_the_default_agent(self, monkeypatch):
        agents = [ScriptedAgent("assistant", TEXT_SCRIPT)]
        with serving(monkeypatch, agents, _AGUIConfig(default_agent="assistant")) as (client, _):
            response = client.post("/agui", headers=AUTH, json=body())
            assert response.status_code == 200
            assert types_of(response)[0] == "RUN_STARTED"


class TestDiscovery:

    def test_lists_only_streaming_capable_agents(self, monkeypatch):
        agents = [ScriptedAgent("streamer"), ScriptedAgent("batch-only", streaming=False)]
        with serving(monkeypatch, agents) as (client, _):
            assert client.get("/agui/agents", headers=AUTH).json() == {"agents": ["streamer"]}

    def test_lists_the_intersection_with_the_agents_allowlist(self, monkeypatch):
        agents = [ScriptedAgent("exposed"), ScriptedAgent("hidden"), ScriptedAgent("batch-only", streaming=False)]
        with serving(monkeypatch, agents, _AGUIConfig(agents=["exposed", "batch-only"])) as (client, _):
            assert client.get("/agui/agents", headers=AUTH).json() == {"agents": ["exposed"]}

    def test_discovery_publishes_names_only(self, monkeypatch):
        """Not agent.get_description(): several adapters return the agent's instructions from it, so
        including it would publish the system prompt, system-tool guidance and all."""
        with serving(monkeypatch, [ScriptedAgent("streamer")]) as (client, _):
            body_text = client.get("/agui/agents", headers=AUTH).text
            assert "description" not in body_text

    def test_discovery_requires_a_token(self, monkeypatch):
        with serving(monkeypatch, [ScriptedAgent()]) as (client, _):
            assert client.get("/agui/agents").status_code == 401


class TestAuthorization:

    def test_a_missing_header_is_401(self, monkeypatch):
        with serving(monkeypatch, [ScriptedAgent()]) as (client, _):
            assert client.post("/agui/assistant", json=body()).status_code == 401

    def test_a_non_bearer_header_is_401(self, monkeypatch):
        with serving(monkeypatch, [ScriptedAgent()]) as (client, _):
            response = client.post("/agui/assistant", headers={"Authorization": "Basic abc"}, json=body())
            assert response.status_code == 401

    def test_a_rejected_token_is_401(self, monkeypatch):
        with serving(monkeypatch, [ScriptedAgent()]) as (client, _):
            response = client.post("/agui/assistant", headers={"Authorization": "Bearer nope"}, json=body())
            assert response.status_code == 401

    def test_identity_reaches_the_run_as_the_acting_user(self, monkeypatch):
        """The authoriser's subject is what hooks and tools attribute the work to."""
        seen = []

        def capture():
            from agentkernel.core.runtime import ACTING_USER_CACHE_KEY

            seen.append(ToolContext.get().session.get_volatile_cache().get(ACTING_USER_CACHE_KEY))

        with serving(monkeypatch, [ScriptedAgent("assistant", [capture])]) as (client, _):
            client.post("/agui/assistant", headers=AUTH, json=body())
        assert seen == ["u1"]


class TestConstructorGuards:

    def test_refuses_to_build_without_an_authoriser(self, monkeypatch):
        """The inherited _resolve_user returns None when unconfigured, which leaves routes open —
        right for thread reads, wrong for a surface that runs agents on a caller's behalf."""
        _install_cfg(monkeypatch, _AGUIConfig())
        with pytest.raises(ValueError, match="never served anonymously"):
            AGUIRequestHandler()

    def test_accepts_an_auth_validator_instead(self, monkeypatch):
        class _Validator(AuthValidator):
            def validate(self, token, context=None):
                return ValidationResult(is_valid=token == GOOD_TOKEN, subject="u1")

        _install_cfg(monkeypatch, _AGUIConfig())
        handler = AGUIRequestHandler(auth_validator=_Validator())
        assert handler._authoriser.authorise(GOOD_TOKEN) == "u1"
        assert handler._authoriser.authorise("nope") is None

    def test_a_default_agent_the_allowlist_hides_is_a_startup_error(self, monkeypatch):
        """A startup error, not a per-request one: the route would exist but always 404."""
        _install_cfg(monkeypatch, _AGUIConfig(agents=["exposed"], default_agent="hidden"))
        with pytest.raises(ValueError, match="agui.default_agent"):
            AGUIRequestHandler(authoriser=StaticAuthoriser())


class TestAgentResolution:

    def test_an_unknown_agent_is_404(self, monkeypatch):
        with serving(monkeypatch, [ScriptedAgent()]) as (client, _):
            assert client.post("/agui/nobody", headers=AUTH, json=body()).status_code == 404

    def test_an_unexposed_agent_is_404_indistinguishable_from_unknown(self, monkeypatch):
        """Identical status *and* detail, so the surface never confirms that a name exists."""
        agents = [ScriptedAgent("exposed"), ScriptedAgent("hidden")]
        with serving(monkeypatch, agents, _AGUIConfig(agents=["exposed"])) as (client, _):
            hidden = client.post("/agui/hidden", headers=AUTH, json=body())
            unknown = client.post("/agui/nobody", headers=AUTH, json=body())
            assert hidden.status_code == unknown.status_code == 404
            assert hidden.json()["detail"].replace("hidden", "X") == unknown.json()["detail"].replace("nobody", "X")

    def test_a_non_streaming_agent_is_400_naming_its_framework(self, monkeypatch):
        """A live path from day one for any app with a CrewAI or smolagents agent, so the message
        has to name the framework and read as pending rather than permanent."""
        agents = [ScriptedAgent("crew", streaming=False, runner_name="crewai")]
        with serving(monkeypatch, agents) as (client, _):
            response = client.post("/agui/crew", headers=AUTH, json=body())
            assert response.status_code == 400
            detail = response.json()["detail"]
            assert "crewai" in detail
            assert "supports_streaming" in detail
            assert "not a permanent limit" in detail


class TestRequestRejection:
    """Every rejection is an HTTP status, not a 200 whose first event is an error."""

    def test_a_body_that_is_not_an_object_is_400(self, monkeypatch):
        with serving(monkeypatch, [ScriptedAgent()]) as (client, _):
            assert client.post("/agui/assistant", headers=AUTH, json=[1, 2]).status_code == 400

    def test_a_body_with_no_user_message_is_400(self, monkeypatch):
        with serving(monkeypatch, [ScriptedAgent()]) as (client, _):
            response = client.post("/agui/assistant", headers=AUTH, json=body(messages=[]))
            assert response.status_code == 400

    def test_an_unknown_content_type_is_400_before_the_stream_opens(self, monkeypatch):
        with serving(monkeypatch, [ScriptedAgent()]) as (client, _):
            message = {"id": "m1", "role": "user", "content": [{"type": "hologram", "text": "x"}]}
            response = client.post("/agui/assistant", headers=AUTH, json=body(messages=[message]))
            assert response.status_code == 400
            assert "data: " not in response.text

    def test_a_rejected_request_leaves_the_session_untouched(self, monkeypatch):
        """A 400 from the mapping must not have written to the session first.

        `to_requests` rejects audio, video and a `binary` part carrying only an id. If
        `set_agui_session_keys` has already run, the rejected request's `state` and `forwardedProps` are
        stored — and because `Runtime.stream` never runs, nothing clears the volatile cache, so the
        *next* run on that thread reads them.
        """
        from agentkernel.integration.agui.state import AGUI_FORWARDED_PROPS_KEY

        with serving(monkeypatch, [ScriptedAgent()]) as (client, runtime):
            message = {
                "id": "m1",
                "role": "user",
                "content": [{"type": "audio", "source": {"type": "data", "value": "AAA", "mimeType": "audio/mpeg"}}],
            }
            rejected = body(messages=[message], state={"leaked": True}, forwardedProps={"leaked": True})

            assert client.post("/agui/assistant", headers=AUTH, json=rejected).status_code == 400

            session = runtime.sessions().load("session-1")
            assert session.get_non_volatile_cache().get(AGUI_STATE_KEY) is None
            assert session.get_volatile_cache().get(AGUI_FORWARDED_PROPS_KEY) is None


class TestMediaType:
    """Routed through the SDK's EventEncoder rather than a hard-coded string. Against the pinned SDK
    get_content_type() ignores Accept entirely, so these pin observed behaviour — the day a release
    starts negotiating, this fails loudly instead of the surface silently changing shape."""

    @pytest.mark.parametrize("accept", ["text/event-stream", "application/vnd.ag-ui.event+proto", "*/*"])
    def test_the_response_media_type_comes_from_the_encoder(self, monkeypatch, accept):
        from ag_ui.encoder import EventEncoder

        headers = {**AUTH, "Accept": accept}
        with serving(monkeypatch, [ScriptedAgent("assistant", TEXT_SCRIPT)]) as (client, _):
            response = client.post("/agui/assistant", headers=headers, json=body())
            assert response.headers["content-type"].startswith(EventEncoder(accept=accept).get_content_type())


class TestRunLifecycle:

    def test_a_successful_run_starts_and_finishes_exactly_once(self, monkeypatch):
        with serving(monkeypatch, [ScriptedAgent("assistant", TEXT_SCRIPT)]) as (client, _):
            response = client.post("/agui/assistant", headers=AUTH, json=body())
            assert types_of(response) == [
                "RUN_STARTED",
                "TEXT_MESSAGE_START",
                "TEXT_MESSAGE_CONTENT",
                "TEXT_MESSAGE_END",
                "RUN_FINISHED",
            ]

    def test_run_started_echoes_the_run_identity(self, monkeypatch):
        with serving(monkeypatch, [ScriptedAgent("assistant", TEXT_SCRIPT)]) as (client, _):
            response = client.post("/agui/assistant", headers=AUTH, json=body(parentRunId="run-0"))
            started = events(response)[0]
            assert (started["threadId"], started["runId"], started["parentRunId"]) == ("session-1", "run-1", "run-0")

    def test_the_thread_id_is_the_session_id(self, monkeypatch):
        with serving(monkeypatch, [ScriptedAgent("assistant", TEXT_SCRIPT)]) as (client, runtime):
            client.post("/agui/assistant", headers=AUTH, json=body(threadId="thread-42"))
            assert runtime.sessions().load("thread-42", strict=True).id == "thread-42"

    def test_an_agent_raising_mid_stream_ends_with_run_error(self, monkeypatch):
        script = [MessageStart(message_id="m1"), TextDelta(message_id="m1", content="hi"), RuntimeError("model exploded")]
        with serving(monkeypatch, [ScriptedAgent("assistant", script)]) as (client, _):
            response = client.post("/agui/assistant", headers=AUTH, json=body())
            assert types_of(response) == ["RUN_STARTED", "TEXT_MESSAGE_START", "TEXT_MESSAGE_CONTENT", "RUN_ERROR"]
            assert "model exploded" in events(response)[-1]["message"]

    def test_a_failed_run_leaves_the_message_unterminated(self, monkeypatch):
        """RunError is AG-UI's terminal event and the protocol imposes no balance requirement, so a
        synthesised TextMessageEnd would assert a completion that did not happen. A handler tracking
        per-run message state to balance the boundaries fails here and nowhere else."""
        script = [MessageStart(message_id="m1"), RuntimeError("boom")]
        with serving(monkeypatch, [ScriptedAgent("assistant", script)]) as (client, _):
            assert "TEXT_MESSAGE_END" not in types_of(client.post("/agui/assistant", headers=AUTH, json=body()))

    def test_a_halted_pre_hook_ends_with_run_error(self, monkeypatch):
        """RunStarted has already been sent when a guardrail rejects, so the halt reply's text
        becomes the RunError message rather than an HTTP status."""
        agent = ScriptedAgent("assistant", TEXT_SCRIPT)
        agent.pre_hooks.append(HaltingPreHook())
        with serving(monkeypatch, [agent]) as (client, _):
            response = client.post("/agui/assistant", headers=AUTH, json=body())
            assert types_of(response) == ["RUN_STARTED", "RUN_ERROR"]
            assert "blocked by policy" in events(response)[-1]["message"]

    def test_an_unmapped_event_is_skipped_rather_than_ending_the_run(self, monkeypatch):
        """to_agui returning None must not become an empty frame or a terminal event."""
        script = [MessageStart(message_id="m1"), ToolCallStart(tool_call_id="t1", name="lookup"), MessageEnd(message_id="m1")]
        with serving(monkeypatch, [ScriptedAgent("assistant", script)]) as (client, _):
            assert types_of(client.post("/agui/assistant", headers=AUTH, json=body()))[-1] == "RUN_FINISHED"


class TestStateSnapshot:

    def test_inbound_state_alone_does_not_emit(self, monkeypatch):
        """State the client just sent is state the client already has. Copying after the inbound
        mapping is what stops every run producing a snapshot."""
        with serving(monkeypatch, [ScriptedAgent("assistant", TEXT_SCRIPT)]) as (client, _):
            response = client.post("/agui/assistant", headers=AUTH, json=body(state={"step": 1}))
            assert "STATE_SNAPSHOT" not in types_of(response)

    def test_no_change_does_not_emit(self, monkeypatch):
        with serving(monkeypatch, [ScriptedAgent("assistant", TEXT_SCRIPT)]) as (client, _):
            response = client.post("/agui/assistant", headers=AUTH, json=body())
            assert "STATE_SNAPSHOT" not in types_of(response)

    def test_a_tool_updating_state_emits_a_snapshot(self, monkeypatch):
        """The deep-copy regression guard. With a live reference instead of a copy, the comparison is
        the mutated dict against itself and this is the only test that notices."""
        script = [MessageStart(message_id="m1"), lambda: AGUIState.update_agui_state('{"step": 2}'), MessageEnd(message_id="m1")]
        with serving(monkeypatch, [ScriptedAgent("assistant", script)]) as (client, _):
            response = client.post("/agui/assistant", headers=AUTH, json=body(state={"step": 1}))
            assert types_of(response) == ["RUN_STARTED", "TEXT_MESSAGE_START", "TEXT_MESSAGE_END", "STATE_SNAPSHOT", "RUN_FINISHED"]
            snapshot = next(e for e in events(response) if e["type"] == "STATE_SNAPSHOT")
            assert snapshot["snapshot"] == {"step": 2}

    def test_a_tool_creating_state_from_nothing_emits_a_snapshot(self, monkeypatch):
        """None != {...}: the common first-run case, and the one a `dict` comparison alone misses."""
        script = [lambda: AGUIState.update_agui_state('{"created": true}')]
        with serving(monkeypatch, [ScriptedAgent("assistant", script)]) as (client, _):
            response = client.post("/agui/assistant", headers=AUTH, json=body())
            assert types_of(response) == ["RUN_STARTED", "STATE_SNAPSHOT", "RUN_FINISHED"]

    def test_the_snapshot_comes_before_the_terminal_event(self, monkeypatch):
        script = [lambda: AGUIState.update_agui_state('{"a": 1}')]
        with serving(monkeypatch, [ScriptedAgent("assistant", script)]) as (client, _):
            types = types_of(client.post("/agui/assistant", headers=AUTH, json=body()))
            assert types.index("STATE_SNAPSHOT") < types.index("RUN_FINISHED")

    def test_a_failed_run_emits_no_snapshot(self, monkeypatch):
        """Runtime.stream only persists the session once the stream drains, so on an error path the
        change was never stored — announcing it would leave the client holding discarded state."""
        script = [lambda: AGUIState.update_agui_state('{"step": 2}'), RuntimeError("boom")]
        with serving(monkeypatch, [ScriptedAgent("assistant", script)]) as (client, _):
            types = types_of(client.post("/agui/assistant", headers=AUTH, json=body()))
            assert "STATE_SNAPSHOT" not in types
            assert types[-1] == "RUN_ERROR"

    def test_state_survives_into_the_next_run(self, monkeypatch):
        """State lives in nv_cache so it outlives the run."""
        script = [lambda: AGUIState.update_agui_state('{"turns": 1}')]
        with serving(monkeypatch, [ScriptedAgent("assistant", script)]) as (client, runtime):
            client.post("/agui/assistant", headers=AUTH, json=body())
            assert runtime.sessions().load("session-1").get_non_volatile_cache().get(AGUI_STATE_KEY) == {"turns": 1}


class TestClientContextDelivery:

    def test_forwarded_props_and_context_reach_a_tool_mid_run(self, monkeypatch):
        seen = {}

        def capture():
            from agentkernel.integration.agui.state import AGUIState

            seen["props"] = AGUIState.get_forwarded_props()
            seen["context"] = AGUIState.get_agui_context()

        with serving(monkeypatch, [ScriptedAgent("assistant", [capture])]) as (client, _):
            client.post(
                "/agui/assistant",
                headers=AUTH,
                json=body(forwardedProps={"page": "/invoices"}, context=[{"description": "open", "value": "invoice-42"}]),
            )
        assert seen["props"] == {"page": "/invoices"}
        assert seen["context"] == [{"description": "open", "value": "invoice-42"}]

    def test_client_context_reaches_a_tool_with_a_copying_store(self, monkeypatch):
        """The design guard for the handler owning the session load. `store()` excludes the volatile
        cache by construction, so props written on one loaded copy can never reach a run that loads
        another — which is every persistent store. In-memory alone would hide it."""
        seen = {}

        def capture():
            from agentkernel.integration.agui.state import AGUIState

            seen["props"] = AGUIState.get_forwarded_props()

        agents = [ScriptedAgent("assistant", [capture])]
        with serving(monkeypatch, agents, store=CopyingSessionStore()) as (client, _):
            client.post("/agui/assistant", headers=AUTH, json=body(forwardedProps={"page": "/invoices"}))
        assert seen["props"] == {"page": "/invoices"}

    def test_client_context_does_not_leak_into_the_next_run(self, monkeypatch):
        """Both are per-request by nature and live in the volatile cache, which Runtime clears."""
        seen = []

        def capture():
            from agentkernel.integration.agui.state import AGUIState

            seen.append(AGUIState.get_forwarded_props())

        with serving(monkeypatch, [ScriptedAgent("assistant", [capture])]) as (client, _):
            client.post("/agui/assistant", headers=AUTH, json=body(forwardedProps={"page": "/invoices"}))
            client.post("/agui/assistant", headers=AUTH, json=body())
        assert seen == [{"page": "/invoices"}, {}]


class TestUnreadableInboundFields:
    """`set_agui_session_keys` writes state/props/context unconditionally, but the tools that read them are
    attached only when the config blocks are enabled — and both default to False. Silence there means
    an app author watches the model ignore data it was sent, with nothing to go on."""

    LOGGER = "ak.integration.agui"

    def test_it_warns_for_each_field_no_tool_can_read(self, monkeypatch, caplog):
        with serving(monkeypatch, [ScriptedAgent()]) as (client, _):
            payload = body(state={"a": 1}, forwardedProps={"page": "/x"}, context=[{"description": "d", "value": "v"}])
            with caplog.at_level(logging.WARNING, logger=self.LOGGER):
                assert client.post("/agui/assistant", headers=AUTH, json=payload).status_code == 200

        warned = " ".join(r.message for r in caplog.records)
        assert "'state'" in warned and "agui.state" in warned
        assert "'forwardedProps'" in warned and "'context'" in warned and "agui.client_context" in warned

    def test_it_stays_silent_when_the_blocks_are_enabled(self, monkeypatch, caplog):
        cfg = _AGUIConfig()
        cfg.state.enabled = True
        cfg.client_context.enabled = True
        with serving(monkeypatch, [ScriptedAgent()], cfg) as (client, _):
            payload = body(state={"a": 1}, forwardedProps={"page": "/x"}, context=[{"description": "d", "value": "v"}])
            with caplog.at_level(logging.WARNING, logger=self.LOGGER):
                assert client.post("/agui/assistant", headers=AUTH, json=payload).status_code == 200

        assert [r.message for r in caplog.records if "is not enabled" in r.message] == []

    def test_it_stays_silent_when_the_client_sent_nothing(self, monkeypatch, caplog):
        """The common shape: `state: null`, `forwardedProps: null`, `context: []`."""
        with serving(monkeypatch, [ScriptedAgent()]) as (client, _):
            with caplog.at_level(logging.WARNING, logger=self.LOGGER):
                assert client.post("/agui/assistant", headers=AUTH, json=body()).status_code == 200

        assert [r.message for r in caplog.records if "is not enabled" in r.message] == []

    def test_the_agents_scope_decides_not_just_the_flag(self, monkeypatch, caplog):
        """Both blocks take an optional `agents` list, so enabled-for-someone-else is still ignored."""
        cfg = _AGUIConfig()
        cfg.client_context.enabled = True
        cfg.client_context.agents = ["someone-else"]
        with serving(monkeypatch, [ScriptedAgent()], cfg) as (client, _):
            with caplog.at_level(logging.WARNING, logger=self.LOGGER):
                assert client.post("/agui/assistant", headers=AUTH, json=body(forwardedProps={"page": "/x"})).status_code == 200

        assert any("'forwardedProps'" in r.message for r in caplog.records)


class TestOptionalDependency:

    def test_a_missing_extra_raises_a_value_error_naming_it(self, monkeypatch):
        """Importing agentkernel without the extra must not fail, so the import lives in __init__
        rather than at module scope — and the error has to say what to install."""
        import builtins

        real_import = builtins.__import__

        def _no_ag_ui(name, *args, **kwargs):
            if name.startswith("ag_ui"):
                raise ImportError("No module named 'ag_ui'")
            return real_import(name, *args, **kwargs)

        _install_cfg(monkeypatch, _AGUIConfig())
        monkeypatch.setattr(builtins, "__import__", _no_ag_ui)
        with pytest.raises(ValueError, match="agui"):
            AGUIRequestHandler(authoriser=StaticAuthoriser())
