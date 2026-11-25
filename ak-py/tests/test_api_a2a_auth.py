"""
A2A authentication hand-off (spec `docs/specs/603-identity-rbac-registry/` 8.7, iteration 8).

The A2A routers are included by `RESTAPI`, so the identity dependency has already put the
principal on `request.state` when the SDK builds its call context; `AKCallContextBuilder` copies
it into the context's state, and the executor reads it from there onto the queued body, falling
back to the request-scoped contextvar and then to the anonymous principal. A card advertises the
configured identity provider's security scheme (iteration 14); the catalog filtering arrives with
the access gate.
"""

import uuid

import httpx
import pytest
from a2a.helpers import get_message_text
from a2a.server.agent_execution import RequestContext
from a2a.server.context import ServerCallContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers.response_helpers import agent_card_to_dict
from a2a.types import Message, Part, Role, SendMessageRequest
from starlette.requests import Request

from agentkernel.api.a2a.a2a import A2A
from agentkernel.api.a2a.handler import AKCallContextBuilder
from agentkernel.api.http import RESTAPI
from agentkernel.core.base import Agent, Runner
from agentkernel.core.builder import A2ACardBuilder
from agentkernel.core.chat_service import ResponseBuilder
from agentkernel.core.config import AKConfig
from agentkernel.core.model import AgentDescriptor, AgentReplyText, AgentSkillDescriptor, Principal
from agentkernel.core.runtime import Runtime
from agentkernel.identity import IdentityProviderFactory, RequestAuthenticator
from agentkernel.pipeline.request_handler import QueuedReply
from agentkernel.secret import SecretManager

AGENT = "triage"
ALICE = Principal(subject="alice", provider="static", namespace="static", groups=["ops"])


class FakeClient:
    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    async def request(self, body, protocol):
        self.calls.append((body, protocol))
        return self.reply


class RecordingEventQueue(EventQueue):
    def __init__(self):
        self.events = []

    async def enqueue_event(self, event) -> None:
        self.events.append(event)


def _reply(text="hi") -> QueuedReply:
    _status, body = ResponseBuilder.build_response(200, "ctx-1", rest_api_mode=False, result=AgentReplyText(response=text))
    return QueuedReply(request_id="r1", status_code=200, body=body)


def _context(call_context: ServerCallContext) -> RequestContext:
    message = Message(message_id=str(uuid.uuid4()), role=Role.ROLE_USER, parts=[Part(text="hello")])
    return RequestContext(call_context, request=SendMessageRequest(message=message), task_id="task-1", context_id="ctx-1")


def _request(principal=None) -> Request:
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/a2a/triage/message:send",
        "headers": [(b"a2a-version", b"1.0")],
        "query_string": b"",
        "state": {},
    }
    request = Request(scope)
    if principal is not None:
        request.state.principal = principal
    return request


@pytest.fixture(autouse=True)
def _a2a_state():
    saved = (dict(A2A._cards), dict(A2A._executors), A2A._built, A2A._client)
    yield
    A2A._cards, A2A._executors, A2A._built, A2A._client = dict(saved[0]), dict(saved[1]), saved[2], saved[3]


class TestCallContextBuilder:
    def test_the_requests_principal_lands_in_the_call_context_state(self):
        context = AKCallContextBuilder().build(_request(ALICE))
        assert context.state["principal"] == ALICE
        assert context.state["headers"]["a2a-version"] == "1.0"  # the SDK's own state is kept

    def test_without_a_principal_the_state_says_none(self):
        assert AKCallContextBuilder().build(_request()).state["principal"] is None


class TestExecutorPrincipal:
    async def _execute(self, call_context: ServerCallContext):
        client = FakeClient(_reply())
        A2A._client = client
        await A2A.Executor(AGENT).execute(_context(call_context), RecordingEventQueue())
        [(body, _)] = client.calls
        return body

    @pytest.mark.asyncio
    async def test_the_call_contexts_principal_rides_the_body(self):
        body = await self._execute(ServerCallContext(state={"principal": ALICE}))
        assert body.principal == ALICE

    @pytest.mark.asyncio
    async def test_the_request_contextvar_is_the_fallback(self):
        token = RequestAuthenticator._current.set(ALICE)
        try:
            body = await self._execute(ServerCallContext())
        finally:
            RequestAuthenticator._current.reset(token)
        assert body.principal == ALICE

    @pytest.mark.asyncio
    async def test_nothing_known_is_the_anonymous_principal(self):
        body = await self._execute(ServerCallContext())
        assert body.principal is not None and body.principal.is_anonymous


class _NoRunner(Runner):
    def __init__(self):
        super().__init__("none")

    async def run(self, agent, session, requests):
        raise AssertionError("the executor must not run the agent here")

    async def stream(self, agent, session, requests):
        raise NotImplementedError()
        yield


class _Agent(Agent):
    def __init__(self, name: str):
        super().__init__(name, _NoRunner())

    def _build_descriptor(self) -> AgentDescriptor:
        return super()._build_descriptor().model_copy(update={"description": "Triages tickets"})

    def get_description(self):
        return "Triages tickets"

    def override_system_prompt(self, prompt):
        pass

    def attach_tool(self, tool):
        pass


class TestOverHttp:
    """Through `RESTAPI.build_app`: the identity dependency, the context builder and the executor in one request."""

    @pytest.fixture
    def served(self, monkeypatch, tmp_path):
        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text(
            "a2a:\n  enabled: true\n  url: http://ak.test/a2a\n"
            "identity:\n  provider:\n    type: static\n    static:\n      principals:\n        ALICE_TOKEN:\n          subject: alice\n          groups: [ops]\n"
        )
        monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", str(cfg_path))
        monkeypatch.setenv("ALICE_TOKEN", "alice-secret")
        AKConfig._reset()
        SecretManager.reset()
        IdentityProviderFactory.reset()
        A2A._cards, A2A._executors, A2A._built = {}, {}, False
        client = FakeClient(_reply("triaged"))
        A2A._client = client
        agent = _Agent(AGENT)
        Runtime.current().register(agent)
        try:
            yield RESTAPI.build_app(handlers=[]), client
        finally:
            Runtime.current().deregister(agent)
            IdentityProviderFactory.reset()
            SecretManager.reset()
            AKConfig._reset()

    async def _send(self, app, headers: dict) -> httpx.Response:
        message = {"messageId": str(uuid.uuid4()), "contextId": "ctx-1", "role": "ROLE_USER", "parts": [{"text": "hello"}]}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://ak.test") as http:
            return await http.post(f"/a2a/{AGENT}/message:send", json={"message": message}, headers={"A2A-Version": "1.0", **headers})

    @pytest.mark.asyncio
    async def test_a_bearer_token_becomes_the_bodys_principal(self, served):
        app, client = served

        response = await self._send(app, {"Authorization": "Bearer alice-secret"})

        assert response.status_code == 200, response.text
        [(body, _)] = client.calls
        assert (body.principal.subject, body.principal.provider, body.principal.groups) == ("alice", "static", ["ops"])

    @pytest.mark.asyncio
    async def test_the_body_says_it_entered_by_a2a(self, served):
        """The route serves only agents on `a2a`; the body says so too, so the runner applies `a2a` and never `rest`
        to a request this surface brought (#603, design refinement 13)."""
        app, client = served

        assert (await self._send(app, {"Authorization": "Bearer alice-secret"})).status_code == 200
        assert client.calls[0][0].surface == "a2a"

    @pytest.mark.asyncio
    async def test_no_token_runs_anonymous(self, served):
        app, client = served

        assert (await self._send(app, {})).status_code == 200
        assert client.calls[0][0].principal.is_anonymous

    @pytest.mark.asyncio
    async def test_a_refused_token_is_a_401_from_the_dependency(self, served):
        app, client = served

        assert (await self._send(app, {"Authorization": "Bearer nope"})).status_code == 401
        assert client.calls == []


class TestCardSecurity:
    """A card advertises the configured identity provider's scheme and requires it; with no provider it declares nothing."""

    DESCRIPTOR = AgentDescriptor(
        id=AGENT, name=AGENT, description="Triages tickets", skills=[AgentSkillDescriptor(id="route", name="route", description="Routes a ticket")]
    )
    REQUIRES_AK = [{"schemes": {"ak": {}}}]

    @pytest.fixture(autouse=True)
    def _no_identity_block(self, monkeypatch):
        monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")
        AKConfig._reset()
        IdentityProviderFactory.reset()
        yield
        IdentityProviderFactory.reset()
        AKConfig._reset()

    def _served(self) -> dict:
        return agent_card_to_dict(A2ACardBuilder.build(self.DESCRIPTOR))

    def test_a_static_provider_is_advertised_as_http_bearer_and_required(self, static_identity):
        served = self._served()

        assert served["securitySchemes"] == {"ak": {"httpAuthSecurityScheme": {"scheme": "bearer"}}}
        assert served["securityRequirements"] == self.REQUIRES_AK

    def test_an_oidc_provider_is_advertised_as_openid_connect_with_its_discovery_url(self, monkeypatch):
        from agentkernel.identity import OIDCIdentityProvider

        provider = OIDCIdentityProvider(issuer="https://issuer.example", audience="ak")
        monkeypatch.setattr(IdentityProviderFactory, "get", classmethod(lambda cls: provider))

        served = self._served()

        assert served["securitySchemes"] == {
            "ak": {"openIdConnectSecurityScheme": {"openIdConnectUrl": "https://issuer.example/.well-known/openid-configuration"}}
        }
        assert served["securityRequirements"] == self.REQUIRES_AK

    def test_every_skill_repeats_the_cards_requirement(self, static_identity):
        [skill] = self._served()["skills"]

        assert skill["securityRequirements"] == self.REQUIRES_AK

    def test_without_an_identity_provider_neither_the_card_nor_a_skill_declares_security(self):
        served = self._served()

        assert "securitySchemes" not in served and "securityRequirements" not in served
        assert "securityRequirements" not in served["skills"][0]


# -- agent access for the caller (#603, plan iteration 20) -----------------------------------------


# `triage` is private, with two tools and a skill that names no tool; `status` is public and granted to nobody;
# `vault` is private and granted to nobody.
TRIAGE = AgentDescriptor(
    id="triage",
    name="triage",
    description="Triages tickets",
    tools=["lookup", "refund"],
    skills=[
        AgentSkillDescriptor(id="lookup", name="lookup", description="Looks a ticket up"),
        AgentSkillDescriptor(id="refund", name="refund", description="Refunds an order"),
        AgentSkillDescriptor(id="ticket-triage", name="Ticket triage", description="Sorts incoming tickets"),
    ],
)
STATUS = AgentDescriptor(id="status", name="status", description="Reports the service status", visibility="public")
VAULT = AgentDescriptor(id="vault", name="vault", description="Keeps secrets")
READ_FOR_ALICE = {"subjects": ["user:alice"], "agents": ["triage"], "level": "read"}
WRITE_FOR_BOB = {"subjects": ["user:bob"], "agents": ["triage"], "level": "write"}
REFUND_NEEDS_WRITE = [{"agent": "triage", "tiers": {"refund": "write"}}]
ALICE_AUTH = {"Authorization": "Bearer alice-secret"}
BOB_AUTH = {"Authorization": "Bearer bob-secret"}
CARD = "/.well-known/agent-card.json"


class TestAgentAccessOverA2A:
    """With an `authorization` block the A2A surface answers for the caller (spec 8.7): the catalog and a card
    are the caller's own, a hidden agent's routes answer like the routes of an agent that is not mounted, and an
    agent the caller sees and holds no level on is a 403 before the executor is reached.

    Through `RESTAPI.build_app`: the identity dependency over a static provider with two callers, the real access
    gate over a static policy, a registry that knows the three agents and hosts none, and the queue client faked."""

    @pytest.fixture
    def served(self, monkeypatch, tmp_path, authorization, descriptor_only_registry):
        from agentkernel.core.session.in_memory import InMemorySessionStore

        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text(
            "a2a:\n  enabled: true\n  url: http://ak.test/a2a\n"
            "identity:\n  provider:\n    type: static\n    static:\n      principals:\n"
            "        ALICE_TOKEN:\n          subject: alice\n        BOB_TOKEN:\n          subject: bob\n"
        )
        monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", str(cfg_path))
        monkeypatch.setenv("ALICE_TOKEN", "alice-secret")
        monkeypatch.setenv("BOB_TOKEN", "bob-secret")
        AKConfig._reset()
        SecretManager.reset()
        IdentityProviderFactory.reset()
        A2A._cards, A2A._descriptors, A2A._executors, A2A._built = {}, {}, {}, False
        client = FakeClient(_reply("triaged"))
        A2A._client = client

        class _Counting(descriptor_only_registry):
            reads = 0

            def descriptor(self, id):
                type(self).reads += 1
                return super().descriptor(id)

            def descriptors(self):
                type(self).reads += 1
                return super().descriptors()

        registry = _Counting([TRIAGE, STATUS, VAULT])
        try:
            with Runtime(InMemorySessionStore(), registry=registry):
                app = RESTAPI.build_app(handlers=[])
                _Counting.reads = 0  # the mount read the registry once; what follows counts the requests
                yield app, client, authorization, _Counting
        finally:
            A2A._descriptors = {}
            IdentityProviderFactory.reset()
            SecretManager.reset()
            AKConfig._reset()

    @staticmethod
    async def _get(app, path: str, headers: dict | None = None) -> httpx.Response:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://ak.test") as http:
            return await http.get(path, headers=headers or {})

    @staticmethod
    async def _send(app, agent: str, headers: dict) -> httpx.Response:
        message = {"messageId": str(uuid.uuid4()), "contextId": "ctx-1", "role": "ROLE_USER", "parts": [{"text": "hello"}]}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://ak.test") as http:
            return await http.post(f"/a2a/{agent}/message:send", json={"message": message}, headers={"A2A-Version": "1.0", **headers})

    @staticmethod
    def _names(response: httpx.Response) -> list[str]:
        return [card["name"] for card in response.json()["cards"]]

    @staticmethod
    def _skills(card: dict) -> list[str]:
        return [skill["id"] for skill in card.get("skills", [])]

    @staticmethod
    def _varies_by(response: httpx.Response) -> list[str]:
        """What a response says it varies by. The app's CORS middleware adds `Origin` to every one."""
        return [value.strip() for value in response.headers.get("vary", "").split(",") if value.strip()]

    # -- the catalog ----------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_the_catalog_is_the_cards_the_caller_may_see(self, served):
        app, _, authorization, _ = served
        authorization(grants=[READ_FOR_ALICE])

        assert self._names(await self._get(app, "/a2a/catalog", ALICE_AUTH)) == ["status", "triage"]
        assert self._names(await self._get(app, "/a2a/catalog", BOB_AUTH)) == ["status"]
        assert self._names(await self._get(app, "/a2a/catalog")) == ["status"]  # nobody authenticated: the anonymous principal

    @pytest.mark.asyncio
    async def test_a_hidden_agent_is_named_nowhere_in_the_catalog(self, served):
        app, _, authorization, _ = served
        authorization(grants=[READ_FOR_ALICE])

        listing = await self._get(app, "/a2a/catalog", BOB_AUTH)

        assert "vault" not in listing.text and "triage" not in listing.text

    @pytest.mark.asyncio
    async def test_a_cards_skills_are_the_ones_the_caller_is_offered(self, served):
        app, _, authorization, _ = served
        authorization(grants=[READ_FOR_ALICE, WRITE_FOR_BOB], tools=REFUND_NEEDS_WRITE)

        for_alice = next(card for card in (await self._get(app, "/a2a/catalog", ALICE_AUTH)).json()["cards"] if card["name"] == "triage")
        for_bob = next(card for card in (await self._get(app, "/a2a/catalog", BOB_AUTH)).json()["cards"] if card["name"] == "triage")

        # `refund` needs write; the skill that names no tool is what the agent does and stays for both.
        assert self._skills(for_alice) == ["lookup", "ticket-triage"]
        assert self._skills(for_bob) == ["lookup", "refund", "ticket-triage"]
        assert {key: value for key, value in for_alice.items() if key != "skills"} == {
            key: value for key, value in for_bob.items() if key != "skills"
        }

    @pytest.mark.asyncio
    async def test_an_agent_seen_by_its_visibility_alone_offers_no_tool_backed_skill(self, served):
        app, _, authorization, _ = served
        authorization(grants=[])
        public_triage = TRIAGE.model_copy(update={"visibility": "public"})
        A2A._descriptors["triage"] = public_triage  # the mounted descriptor, as a public agent's would be

        [card] = [card for card in (await self._get(app, "/a2a/catalog", BOB_AUTH)).json()["cards"] if card["name"] == "triage"]

        assert self._skills(card) == ["ticket-triage"]

    @pytest.mark.asyncio
    async def test_the_catalog_says_it_varies_by_caller(self, served):
        app, _, authorization, _ = served
        authorization(grants=[READ_FOR_ALICE])

        assert "Authorization" in self._varies_by(await self._get(app, "/a2a/catalog", ALICE_AUTH))

    @pytest.mark.asyncio
    async def test_the_catalog_is_decided_from_the_mounted_cards_without_reading_the_registry(self, served):
        app, _, authorization, registry = served
        authorization(grants=[READ_FOR_ALICE])

        await self._get(app, "/a2a/catalog", ALICE_AUTH)

        assert registry.reads == 0

    # -- the well-known card ----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_a_hidden_agents_card_is_the_404_of_an_agent_that_is_not_mounted(self, served):
        app, _, authorization, _ = served
        authorization(grants=[READ_FOR_ALICE])

        hidden = await self._get(app, f"/a2a/vault{CARD}", BOB_AUTH)
        unknown = await self._get(app, f"/a2a/ghost{CARD}", BOB_AUTH)

        assert hidden.status_code == unknown.status_code == 404
        assert hidden.content == unknown.content
        assert dict(hidden.headers) == dict(unknown.headers)

    @pytest.mark.asyncio
    async def test_a_card_is_served_to_a_caller_who_sees_the_agent_and_holds_no_level(self, served):
        # A card says what an agent is; using it is the 403 below.
        app, _, authorization, _ = served
        authorization(grants=[READ_FOR_ALICE])

        card = await self._get(app, f"/a2a/status{CARD}", BOB_AUTH)

        assert (card.status_code, card.json()["name"]) == (200, "status")

    @pytest.mark.asyncio
    async def test_a_served_card_is_narrowed_and_its_etag_is_of_the_card_as_served(self, served):
        app, _, authorization, _ = served
        authorization(grants=[READ_FOR_ALICE, WRITE_FOR_BOB], tools=REFUND_NEEDS_WRITE)

        for_alice = await self._get(app, f"/a2a/triage{CARD}", ALICE_AUTH)
        for_bob = await self._get(app, f"/a2a/triage{CARD}", BOB_AUTH)

        assert (self._skills(for_alice.json()), self._skills(for_bob.json())) == (["lookup", "ticket-triage"], ["lookup", "refund", "ticket-triage"])
        assert for_alice.headers["etag"] != for_bob.headers["etag"]
        assert "Authorization" in self._varies_by(for_alice) and "Authorization" in self._varies_by(for_bob)

    @pytest.mark.asyncio
    async def test_a_conditional_request_is_answered_for_the_card_its_caller_is_served(self, served):
        app, _, authorization, _ = served
        authorization(grants=[READ_FOR_ALICE, WRITE_FOR_BOB], tools=REFUND_NEEDS_WRITE)
        alices = (await self._get(app, f"/a2a/triage{CARD}", ALICE_AUTH)).headers["etag"]

        same_caller = await self._get(app, f"/a2a/triage{CARD}", {**ALICE_AUTH, "If-None-Match": alices})
        other_caller = await self._get(app, f"/a2a/triage{CARD}", {**BOB_AUTH, "If-None-Match": alices})

        # A cache holding alice's card must not be told it is still good for bob.
        assert same_caller.status_code == 304 and "Authorization" in self._varies_by(same_caller)
        assert other_caller.status_code == 200

    # -- the protocol routes ---------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_a_message_for_a_hidden_agent_is_the_404_of_an_agent_that_is_not_mounted(self, served):
        app, client, authorization, registry = served
        authorization(grants=[READ_FOR_ALICE])

        hidden = await self._send(app, "vault", BOB_AUTH)
        unknown = await self._send(app, "ghost", BOB_AUTH)

        assert hidden.status_code == unknown.status_code == 404
        assert hidden.content == unknown.content
        assert dict(hidden.headers) == dict(unknown.headers)
        assert client.calls == []
        assert registry.reads == 0  # decided from the descriptor the route was mounted with

    @pytest.mark.asyncio
    async def test_a_message_for_an_agent_the_caller_sees_and_may_not_use_is_a_403(self, served):
        app, client, authorization, _ = served
        authorization(grants=[READ_FOR_ALICE])

        response = await self._send(app, "status", BOB_AUTH)

        assert response.status_code == 403
        assert response.json() == {"detail": "Principal 'bob' holds no level on agent 'status'"}
        assert client.calls == []

    @pytest.mark.asyncio
    async def test_a_caller_with_a_level_is_served_as_itself(self, served):
        app, client, authorization, _ = served
        authorization(grants=[READ_FOR_ALICE])

        response = await self._send(app, "triage", ALICE_AUTH)

        assert response.status_code == 200, response.text
        [(body, _)] = client.calls
        assert (body.agent, body.principal.subject) == ("triage", "alice")

    @pytest.mark.asyncio
    async def test_a_request_nobody_authenticated_is_the_anonymous_principal(self, served):
        app, client, authorization, _ = served
        authorization(grants=[READ_FOR_ALICE])

        assert (await self._send(app, "triage", {})).status_code == 404
        assert (await self._send(app, "status", {})).status_code == 403
        assert client.calls == []

    @pytest.mark.asyncio
    async def test_every_route_of_an_agent_is_behind_the_same_answer(self, served):
        # Tasks are the agent's too: reading one is using the agent.
        app, _, authorization, _ = served
        authorization(grants=[READ_FOR_ALICE])

        hidden = await self._get(app, "/a2a/vault/tasks/t-1", {**BOB_AUTH, "A2A-Version": "1.0"})
        forbidden = await self._get(app, "/a2a/status/tasks/t-1", {**BOB_AUTH, "A2A-Version": "1.0"})
        unknown = await self._get(app, "/a2a/ghost/tasks/t-1", {**BOB_AUTH, "A2A-Version": "1.0"})

        assert (hidden.status_code, forbidden.status_code) == (404, 403)
        assert hidden.content == unknown.content

    # -- failing closed -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_a_caller_that_names_nobody_is_listed_as_the_anonymous_principal(self, served):
        _, _, authorization, _ = served
        authorization(grants=[READ_FOR_ALICE])

        # A caller of `get_cards` that forgets the principal is listed less, never more.
        assert [card.name for card in A2A.get_cards()] == ["status"]
        assert await A2A.card_for(None, "triage") is None

    @pytest.mark.asyncio
    async def test_a_card_with_no_descriptor_to_decide_by_is_served_to_nobody(self, served):
        app, _, authorization, _ = served
        authorization(grants=[READ_FOR_ALICE])
        del A2A._descriptors["triage"]  # a card mounted some other way: there is nothing to judge visibility by

        assert await A2A.card_for(ALICE, "triage") is None
        assert (await self._get(app, f"/a2a/triage{CARD}", ALICE_AUTH)).status_code == 404

    @pytest.mark.asyncio
    async def test_the_card_is_decided_once_for_a_request(self, served, monkeypatch):
        app, _, authorization, _ = served
        authorization(grants=[READ_FOR_ALICE])
        asked = []
        card_for = A2A.card_for.__func__

        async def _counting(cls, principal, name):
            asked.append(name)
            return await card_for(cls, principal, name)

        monkeypatch.setattr(A2A, "card_for", classmethod(_counting))

        await self._get(app, f"/a2a/triage{CARD}", ALICE_AUTH)

        assert asked == ["triage"]

    # -- without the block -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_without_an_authorization_block_the_surface_is_as_it_was(self, served):
        app, client, _, _ = served

        listing = await self._get(app, "/a2a/catalog", BOB_AUTH)
        card = await self._get(app, f"/a2a/vault{CARD}", BOB_AUTH)

        assert self._names(listing) == ["status", "triage", "vault"]
        assert self._skills(next(c for c in listing.json()["cards"] if c["name"] == "triage")) == ["lookup", "refund", "ticket-triage"]
        assert "Authorization" not in self._varies_by(listing) and "Authorization" not in self._varies_by(card)
        assert (card.status_code, "etag" in card.headers) == (200, True)
        assert (await self._send(app, "vault", BOB_AUTH)).status_code == 200
        assert client.calls[0][0].agent == "vault"


class TestTheCallerOfARequest:
    """Who an A2A request acts as: the principal the identity dependency put on the request, else the one it
    left in the request's context, else nobody."""

    def test_the_principal_on_the_request_is_the_caller(self):
        from agentkernel.api.a2a.handler import A2ARESTRequestHandler

        token = RequestAuthenticator._current.set(Principal(subject="someone-else", provider="static", namespace="static"))
        try:
            assert A2ARESTRequestHandler._caller(_request(ALICE)) == ALICE
        finally:
            RequestAuthenticator._current.reset(token)

    def test_the_request_context_is_the_fallback_and_then_nobody(self):
        from agentkernel.api.a2a.handler import A2ARESTRequestHandler

        token = RequestAuthenticator._current.set(ALICE)
        try:
            assert A2ARESTRequestHandler._caller(_request()) == ALICE
        finally:
            RequestAuthenticator._current.reset(token)
        assert A2ARESTRequestHandler._caller(_request()).is_anonymous

    @pytest.mark.parametrize(
        "already, expected",
        [(None, "Authorization"), ("Origin", "Origin, Authorization"), ("Origin, authorization", "Origin, authorization")],
        ids=["none", "kept", "not-repeated"],
    )
    def test_a_response_that_varies_by_caller_keeps_what_it_already_varies_by(self, already, expected):
        from starlette.responses import Response

        from agentkernel.api.a2a.handler import A2ARESTRequestHandler

        response = Response(headers={"Vary": already} if already else None)

        A2ARESTRequestHandler._vary_by_caller(response)

        assert response.headers["vary"] == expected
