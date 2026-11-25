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
from unittest.mock import patch

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from agentkernel.core.base import Agent, Runner, Session
from agentkernel.core.config import _AGUIConfig, _GuardrailConfig, _RegistryConfig
from agentkernel.core.event import MessageEnd, MessageStart, TextDelta, ToolCallStart
from agentkernel.core.hooks import PreHook
from agentkernel.core.model import AgentDescriptor, AgentReplyText, Principal
from agentkernel.core.registry import InMemoryAgentRegistry
from agentkernel.core.runtime import Runtime
from agentkernel.core.session.in_memory import InMemorySessionStore
from agentkernel.core.tool import ToolContext
from agentkernel.core.util.factory import AKConfigError
from agentkernel.identity import AuthenticationError, IdentityProvider, IdentityProviderFactory, RequestAuthenticator
from agentkernel.integration.agui import AGUIRequestHandler
from agentkernel.integration.agui.state import AGUI_STATE_KEY, AGUIState

GOOD_TOKEN = "good-token"
AUTH = {"Authorization": f"Bearer {GOOD_TOKEN}"}


class _TestProvider(IdentityProvider):
    """Accepts exactly one token, so 401 has a live path in every test below."""

    name = "test"

    async def authenticate(self, credential, context=None):
        if credential == GOOD_TOKEN:
            return Principal(subject="u1", provider=self.name, namespace="test", groups=["ops"])
        raise AuthenticationError("nope")


def _with_provider(monkeypatch, provider=None):
    """Stand the configured identity provider in: the handler requires one at construction."""
    monkeypatch.setattr(IdentityProviderFactory, "get", classmethod(lambda cls: provider))
    return provider


class PrincipalRecordingRunner(Runner):
    """Streams one message and records the principal Runtime published for the run."""

    def __init__(self):
        super().__init__("recording")
        self.seen = []

    @property
    def supports_streaming(self) -> bool:
        return True

    async def run(self, agent, session, requests):
        return AgentReplyText(response="unused")

    async def stream(self, agent, session, requests):
        self.seen.append(session.get_principal())
        yield MessageStart(message_id="m1")
        yield TextDelta(message_id="m1", content="hi")
        yield MessageEnd(message_id="m1")


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


def _hidden_from_agui(*agent_ids: str) -> _RegistryConfig:
    """A registry block whose overlay keeps the named agents off the AG-UI surface."""
    return _RegistryConfig(agents={agent_id: {"surfaces": ["rest", "a2a", "mcp"]} for agent_id in agent_ids})


def _install_cfg(monkeypatch, agui_cfg, registry_cfg=None):
    """Point AKConfig.get() at a stub carrying every section this path reads."""

    class _Cfg:
        agui = agui_cfg
        identity = None
        registry = registry_cfg
        authorization = None
        multimodal = None
        sandbox = None
        guardrail = _GuardrailConfig()

        class session:
            type = "in_memory"

    monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: _Cfg))


class _SharedRegistry(InMemoryAgentRegistry):
    """A registry over a shared store: it hosts what registers here and also knows `remote`, a streaming agent
    another process registered."""

    REMOTE = AgentDescriptor(id="remote", name="remote", runner="openai", supports_streaming=True)

    def descriptor(self, id):
        return super().descriptor(id) or (self.REMOTE if id == self.REMOTE.id else None)

    def descriptors(self):
        return [*super().descriptors(), self.REMOTE]


@contextmanager
def serving(monkeypatch, agents, agui_cfg=None, store=None, registry_cfg=None, registry=None, provider=None):
    """Mount the AG-UI router over a runtime holding the given agents, behind the identity dependency.

    ``registry_cfg`` is the `registry` configuration block (its overlay sets an agent's surfaces);
    ``registry`` replaces the runtime's registry outright, for agents this process does not host;
    ``provider`` replaces the one-token identity provider, for a test with more than one caller.
    """
    _install_cfg(monkeypatch, agui_cfg if agui_cfg is not None else _AGUIConfig(), registry_cfg)
    provider = _with_provider(monkeypatch, provider or _TestProvider())
    Runtime._system_pre_hooks = []
    Runtime._system_post_hooks = []
    runtime = Runtime(store if store is not None else InMemorySessionStore(), registry=registry)
    for agent in agents:
        runtime.register(agent)
    try:
        with runtime:
            app = FastAPI()
            app.include_router(AGUIRequestHandler().get_router(), dependencies=[Depends(RequestAuthenticator(provider).dependency())])
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

    def test_lists_only_the_streaming_agents_exposed_on_agui(self, monkeypatch):
        agents = [ScriptedAgent("exposed"), ScriptedAgent("hidden"), ScriptedAgent("batch-only", streaming=False)]
        with serving(monkeypatch, agents, registry_cfg=_hidden_from_agui("hidden")) as (client, _):
            assert client.get("/agui/agents", headers=AUTH).json() == {"agents": ["exposed"]}

    def test_lists_in_id_order_whatever_the_registration_order(self, monkeypatch):
        with serving(monkeypatch, [ScriptedAgent("support"), ScriptedAgent("billing")]) as (client, _):
            assert client.get("/agui/agents", headers=AUTH).json() == {"agents": ["billing", "support"]}

    def test_lists_only_the_agents_this_process_hosts(self, monkeypatch):
        """This handler runs agents itself. One a shared registry knows from another process cannot be run here,
        so listing it would advertise an agent every run of which fails; the queue-mode handler lists those."""
        with serving(monkeypatch, [ScriptedAgent("local")], registry=_SharedRegistry()) as (client, _):
            assert client.get("/agui/agents", headers=AUTH).json() == {"agents": ["local"]}

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

    def test_the_authenticated_principal_reaches_the_run(self, monkeypatch):
        """What the token resolved to is what Runtime publishes for the run (#603)."""
        runner = PrincipalRecordingRunner()
        agent = ScriptedAgent("recorder")
        agent._runner = runner
        with serving(monkeypatch, [agent]) as (client, _):
            assert client.post("/agui/recorder", headers=AUTH, json=body()).status_code == 200

        [principal] = runner.seen
        assert (principal.subject, principal.provider, principal.groups) == ("u1", "test", ["ops"])


class TestConstructorGuards:

    def test_refuses_to_build_without_an_identity_block(self, monkeypatch):
        """A surface that runs agents on a caller's behalf is never served anonymously: with nobody
        able to authenticate, mounting it is a configuration error, not an open route."""
        _install_cfg(monkeypatch, _AGUIConfig())
        _with_provider(monkeypatch, None)
        with pytest.raises(AKConfigError, match="requires an identity block"):
            AGUIRequestHandler()

    def test_a_default_agent_not_exposed_on_agui_is_a_startup_error(self, monkeypatch):
        """A startup error, not a per-request one: the route would exist but always 404."""
        _install_cfg(monkeypatch, _AGUIConfig(default_agent="hidden"), _hidden_from_agui("hidden"))
        _with_provider(monkeypatch, _TestProvider())
        runtime = Runtime(InMemorySessionStore())
        runtime.register(ScriptedAgent("hidden"))
        with runtime:
            with pytest.raises(ValueError, match="agui.default_agent is 'hidden'.*registry.agents.hidden.surfaces"):
                AGUIRequestHandler()

    def test_a_default_agent_the_registry_does_not_know_is_a_startup_error(self, monkeypatch):
        _install_cfg(monkeypatch, _AGUIConfig(default_agent="nobody"))
        _with_provider(monkeypatch, _TestProvider())
        with Runtime(InMemorySessionStore()):
            with pytest.raises(ValueError, match="agui.default_agent is 'nobody'"):
                AGUIRequestHandler()

    def test_a_default_agent_another_process_hosts_is_a_startup_error(self, monkeypatch):
        """The bare route would exist and answer 404 on every call: this handler serves only what it hosts."""
        _install_cfg(monkeypatch, _AGUIConfig(default_agent="remote"))
        _with_provider(monkeypatch, _TestProvider())
        with Runtime(InMemorySessionStore(), registry=_SharedRegistry()):
            with pytest.raises(ValueError, match="agui.default_agent is 'remote'.*AGUIPipelineRequestHandler"):
                AGUIRequestHandler()


class TestAgentResolution:

    def test_an_unknown_agent_is_404(self, monkeypatch):
        with serving(monkeypatch, [ScriptedAgent()]) as (client, _):
            assert client.post("/agui/nobody", headers=AUTH, json=body()).status_code == 404

    def test_an_unexposed_agent_is_404_indistinguishable_from_unknown(self, monkeypatch):
        """Identical status *and* detail, so the surface never confirms that a name exists."""
        agents = [ScriptedAgent("exposed"), ScriptedAgent("hidden")]
        with serving(monkeypatch, agents, registry_cfg=_hidden_from_agui("hidden")) as (client, _):
            hidden = client.post("/agui/hidden", headers=AUTH, json=body())
            unknown = client.post("/agui/nobody", headers=AUTH, json=body())
            assert hidden.status_code == unknown.status_code == 404
            assert hidden.json()["detail"].replace("hidden", "X") == unknown.json()["detail"].replace("nobody", "X")

    def test_a_hosted_agent_is_resolved_from_its_own_descriptor_without_reading_the_registry_store(self, monkeypatch):
        """Over a shared registry a store read per run would be a network round trip for an agent this process holds."""

        class _NoStoreReads(InMemoryAgentRegistry):
            def descriptor(self, id):
                raise AssertionError("the registry's store was read for an agent this process hosts")

        with serving(monkeypatch, [ScriptedAgent("assistant", TEXT_SCRIPT)], registry=_NoStoreReads()) as (client, _):
            response = client.post("/agui/assistant", headers=AUTH, json=body())
            assert response.status_code == 200
            assert types_of(response)[-1] == "RUN_FINISHED"

    def test_an_agent_another_process_hosts_is_404_like_one_that_does_not_exist(self, monkeypatch):
        """Not the 500 a run that cannot select its agent ends in: this handler does not serve the agent at all,
        and says so the way it does for any name it does not serve."""
        with serving(monkeypatch, [ScriptedAgent("local")], registry=_SharedRegistry()) as (client, _):
            remote = client.post("/agui/remote", headers=AUTH, json=body())
            unknown = client.post("/agui/nobody", headers=AUTH, json=body())
            assert remote.status_code == unknown.status_code == 404
            assert remote.json()["detail"].replace("remote", "X") == unknown.json()["detail"].replace("nobody", "X")

    def test_a_run_is_prepared_as_a_request_that_entered_by_agui(self, monkeypatch):
        """An agent on `agui` only runs here, where a REST chat request naming it is refused (#603, design
        refinement 13): the handler says which surface the run came in by, and the selection applies that one."""
        from agentkernel.core.chat_service import ChatService

        prepared_with = []
        prepare = ChatService.prepare_agent_handler

        def _spy(self, session_id, agent, surface=None, principal=None):
            prepared_with.append(surface)
            return prepare(self, session_id, agent, surface=surface, principal=principal)

        monkeypatch.setattr(ChatService, "prepare_agent_handler", _spy)
        agui_only = _RegistryConfig(agents={"assistant": {"surfaces": ["agui"]}})

        with serving(monkeypatch, [ScriptedAgent("assistant", TEXT_SCRIPT)], registry_cfg=agui_only) as (client, _):
            response = client.post("/agui/assistant", headers=AUTH, json=body())
            assert types_of(response)[-1] == "RUN_FINISHED"

        assert prepared_with == ["agui"]

    def test_with_authorization_the_run_is_prepared_for_the_caller_not_for_nobody(self, monkeypatch, authorization):
        """The handler hands the caller's principal to the pre-run check, so a caller the policy names is served
        (#603, iteration 18). Checked as nobody, it would be refused an agent only it is granted."""
        with serving(monkeypatch, [ScriptedAgent("assistant", TEXT_SCRIPT)]) as (client, _):
            authorization(grants=[{"subjects": ["group:ops"], "agents": ["assistant"], "level": "read"}])
            response = client.post("/agui/assistant", headers=AUTH, json=body())

            assert response.status_code == 200
            assert types_of(response)[-1] == "RUN_FINISHED"

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


OTHER_AUTH = {"Authorization": "Bearer other-token"}


class _TwoCallers(_TestProvider):
    """The one-token provider plus a second caller, `u2`, who is in no group."""

    async def authenticate(self, credential, context=None):
        if credential == "other-token":
            return Principal(subject="u2", provider=self.name, namespace="test")
        return await super().authenticate(credential, context)


class TestAgentAccessOverAGUI:
    """With an `authorization` block the AG-UI routes answer for the caller (spec 8.5, plan iteration 20): the
    listing is the agents it may see, a run for one it may not see is the unknown agent's 404, and a run for one
    it sees and holds no level on is a 403, each before any session is loaded or stream opened.

    `assistant` is private and granted to the ops group (u1 is in it, u2 is not); `status` is public and granted
    to nobody; `vault` is private and granted to nobody."""

    GRANTS = [{"subjects": ["group:ops"], "agents": ["assistant"], "level": "read"}]

    @staticmethod
    def _agents():
        status = ScriptedAgent("status", TEXT_SCRIPT)
        status._set_descriptor(status.descriptor.model_copy(update={"visibility": "public"}))
        return [ScriptedAgent("assistant", TEXT_SCRIPT), status, ScriptedAgent("vault", TEXT_SCRIPT)]

    def test_the_listing_is_the_agents_the_caller_may_see(self, monkeypatch, authorization):
        with serving(monkeypatch, self._agents(), provider=_TwoCallers()) as (client, _):
            authorization(grants=self.GRANTS)

            assert client.get("/agui/agents", headers=AUTH).json() == {"agents": ["assistant", "status"]}
            assert client.get("/agui/agents", headers=OTHER_AUTH).json() == {"agents": ["status"]}

    def test_the_listing_still_leaves_out_what_agui_does_not_serve(self, monkeypatch, authorization):
        agents = [*self._agents(), ScriptedAgent("batch-only", streaming=False), ScriptedAgent("elsewhere", TEXT_SCRIPT)]
        with serving(monkeypatch, agents, provider=_TwoCallers(), registry_cfg=_hidden_from_agui("elsewhere")) as (client, _):
            authorization(grants=[{"subjects": ["group:ops"], "agents": ["*"], "level": "read"}])

            assert client.get("/agui/agents", headers=AUTH).json() == {"agents": ["assistant", "status", "vault"]}

    def test_the_listing_is_among_the_hosted_agents_without_listing_the_registrys_store(self, monkeypatch, authorization):
        class _NoStoreListing(InMemoryAgentRegistry):
            def descriptors(self):
                raise AssertionError("the registry's store was listed by a handler that serves only what it hosts")

        with serving(monkeypatch, self._agents(), provider=_TwoCallers(), registry=_NoStoreListing()) as (client, _):
            authorization(grants=self.GRANTS)

            assert client.get("/agui/agents", headers=OTHER_AUTH).json() == {"agents": ["status"]}

    def test_a_run_for_a_hidden_agent_is_the_unknown_agents_404(self, monkeypatch, authorization):
        with serving(monkeypatch, self._agents(), provider=_TwoCallers()) as (client, _):
            authorization(grants=self.GRANTS)

            hidden = client.post("/agui/assistant", headers=OTHER_AUTH, json=body())
            unknown = client.post("/agui/nobody", headers=OTHER_AUTH, json=body())

            assert hidden.status_code == unknown.status_code == 404
            # One answer but for the name the caller sent.
            assert hidden.text.replace("assistant", "nobody") == unknown.text
            assert dict(hidden.headers) == {**dict(unknown.headers), "content-length": hidden.headers["content-length"]}

    def test_a_run_for_an_agent_the_caller_sees_and_may_not_use_is_a_403(self, monkeypatch, authorization):
        with serving(monkeypatch, self._agents(), provider=_TwoCallers()) as (client, runtime):
            authorization(grants=self.GRANTS)
            store = runtime.sessions()
            with patch.object(store, "load", wraps=store.load) as load:
                response = client.post("/agui/status", headers=OTHER_AUTH, json=body())

            assert response.status_code == 403
            assert response.json() == {"detail": "Principal 'u2' holds no level on agent 'status'"}
            load.assert_not_called()  # refused before a session is loaded or a stream opened

    def test_a_caller_with_a_level_runs_the_agent(self, monkeypatch, authorization):
        with serving(monkeypatch, self._agents(), provider=_TwoCallers()) as (client, _):
            authorization(grants=self.GRANTS)

            response = client.post("/agui/assistant", headers=AUTH, json=body())

            assert response.status_code == 200
            assert types_of(response)[-1] == "RUN_FINISHED"

    def test_a_hidden_agent_that_cannot_stream_is_still_a_404(self, monkeypatch, authorization):
        # The 400 names the agent's framework: answered first, it would say the name exists.
        agents = [*self._agents(), ScriptedAgent("crew", streaming=False, runner_name="crewai")]
        with serving(monkeypatch, agents, provider=_TwoCallers()) as (client, _):
            authorization(grants=self.GRANTS)

            response = client.post("/agui/crew", headers=OTHER_AUTH, json=body())

            assert (response.status_code, "crewai" in response.text) == (404, False)

    def test_a_default_agent_the_caller_may_not_see_is_the_404_of_a_route_with_no_default(self, monkeypatch, authorization):
        """The caller named no agent, so the answer names none: it is what the bare route answers when no
        default agent is configured at all."""
        with serving(monkeypatch, self._agents(), provider=_TwoCallers()) as (client, _):
            unconfigured = client.post("/agui", headers=OTHER_AUTH, json=body())
        with serving(monkeypatch, self._agents(), _AGUIConfig(default_agent="assistant"), provider=_TwoCallers()) as (client, _):
            authorization(grants=self.GRANTS)
            hidden = client.post("/agui", headers=OTHER_AUTH, json=body())
            served = client.post("/agui", headers=AUTH, json=body())

        assert hidden.status_code == unconfigured.status_code == 404
        assert hidden.content == unconfigured.content and "assistant" not in hidden.text
        assert served.status_code == 200

    def test_a_default_agent_the_caller_sees_and_may_not_use_is_still_a_403(self, monkeypatch, authorization):
        # Only the 404 is made anonymous: a caller who can see the default agent is told why it may not run it.
        with serving(monkeypatch, self._agents(), _AGUIConfig(default_agent="status"), provider=_TwoCallers()) as (client, _):
            authorization(grants=self.GRANTS)

            response = client.post("/agui", headers=OTHER_AUTH, json=body())

            assert (response.status_code, response.json()) == (403, {"detail": "Principal 'u2' holds no level on agent 'status'"})

    def test_mounting_the_routes_checks_the_policy_against_the_hosted_agents(self, monkeypatch, authorization):
        """An app that serves its agents over AG-UI alone mounts no chat router, so this is where its policy is
        compared with the agents it hosts and the registry (#603, spec 7): one that cannot be enforced stops the mount."""
        from agentkernel.core.util.factory import AKConfigError

        class _WithTools(ScriptedAgent):
            def get_tool_names(self):
                return ["lookup"]

        _install_cfg(monkeypatch, _AGUIConfig())
        _with_provider(monkeypatch, _TestProvider())
        runtime = Runtime(InMemorySessionStore())
        runtime.register(_WithTools("assistant", TEXT_SCRIPT))
        with runtime:
            handler = AGUIRequestHandler()
            authorization(grants=self.GRANTS, tools=[{"agent": "assistant", "deny": ["lokup"]}])

            with pytest.raises(AKConfigError, match=r"authorization\.static\.tools\[0\] names tools agent 'assistant' does not have"):
                handler.get_router()

    def test_without_an_authorization_block_nothing_is_asked(self, monkeypatch):
        with serving(monkeypatch, self._agents(), provider=_TwoCallers()) as (client, _):
            assert client.get("/agui/agents", headers=OTHER_AUTH).json() == {"agents": ["assistant", "status", "vault"]}
            assert client.post("/agui/vault", headers=OTHER_AUTH, json=body()).status_code == 200


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
        _with_provider(monkeypatch, _TestProvider())
        monkeypatch.setattr(builtins, "__import__", _no_ag_ui)
        with pytest.raises(ValueError, match="agui"):
            AGUIRequestHandler()
