"""
A2A authentication hand-off (spec `docs/specs/603-identity-rbac-registry/` 8.7, iteration 8).

The A2A routers are included by `RESTAPI`, so the identity dependency has already put the
principal on `request.state` when the SDK builds its call context; `AKCallContextBuilder` copies
it into the context's state, and the executor reads it from there onto the queued body, falling
back to the request-scoped contextvar and then to the anonymous principal. The cards' security
schemes and the catalog filtering arrive with the registry and the access gate.
"""

import uuid

import httpx
import pytest
from a2a.helpers import get_message_text
from a2a.server.agent_execution import RequestContext
from a2a.server.context import ServerCallContext
from a2a.server.events import EventQueue
from a2a.types import Message, Part, Role, SendMessageRequest
from starlette.requests import Request

from agentkernel.api.a2a.a2a import A2A
from agentkernel.api.a2a.handler import AKCallContextBuilder
from agentkernel.api.http import RESTAPI
from agentkernel.core.base import Agent, Runner
from agentkernel.core.builder import A2ACardBuilder
from agentkernel.core.chat_service import ResponseBuilder
from agentkernel.core.config import AKConfig
from agentkernel.core.model import AgentReplyText, Principal
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

    def get_a2a_card(self):
        return A2ACardBuilder.build(name=self.name, description="Triages tickets", skills=[])

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
    async def test_no_token_runs_anonymous(self, served):
        app, client = served

        assert (await self._send(app, {})).status_code == 200
        assert client.calls[0][0].principal.is_anonymous

    @pytest.mark.asyncio
    async def test_a_refused_token_is_a_401_from_the_dependency(self, served):
        app, client = served

        assert (await self._send(app, {"Authorization": "Bearer nope"})).status_code == 401
        assert client.calls == []
