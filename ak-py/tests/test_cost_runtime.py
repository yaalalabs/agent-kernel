"""
Runtime seams of cost management (spec `docs/specs/954-pluggable-cost-management/`, §3).

Iteration 1.5: every run carries a request id, from the request through ChatService, AgentService and Runtime,
minted when absent and published as Session.get_request_id() for the run's duration.
"""

import re

import pytest

from agentkernel.core.base import Agent, Runner, Session
from agentkernel.core.chat_service import AgentHandler, ChatService
from agentkernel.core.event import MessageEnd, MessageStart, TextDelta
from agentkernel.core.model import AgentReplyText, AgentRequestText, BaseRequest, BaseRunRequest
from agentkernel.core.runtime import Runtime
from agentkernel.core.service import AgentService
from agentkernel.core.session.in_memory import InMemorySessionStore


class RequestIdRunner(Runner):
    """Records the request id the session publishes while the run is in progress."""

    def __init__(self):
        super().__init__("request-id")
        self.seen: list[str | None] = []

    async def run(self, agent, session: Session, requests):
        self.seen.append(session.get_request_id())
        return AgentReplyText(response="ok")

    async def stream(self, agent, session: Session, requests):
        self.seen.append(session.get_request_id())
        yield MessageStart(message_id="m1")
        yield TextDelta(message_id="m1", content="ok")
        yield MessageEnd(message_id="m1")


class SimpleAgent(Agent):
    def __init__(self, runner: Runner):
        super().__init__("assistant", runner)

    def get_description(self) -> str:
        return "test agent"

    def get_a2a_card(self):
        return None

    def override_system_prompt(self, prompt):
        pass

    def attach_tool(self, tool):
        pass


@pytest.fixture
def runtime():
    return Runtime(InMemorySessionStore())


@pytest.fixture
def agent(runtime):
    agent = SimpleAgent(RequestIdRunner())
    runtime.register(agent)
    return agent


_REQUESTS = [AgentRequestText(prompt="hi")]


class TestFromPayload:
    def test_an_envelope_body_takes_the_envelope_id(self):
        envelope = BaseRequest.from_payload({"request_id": "env-1", "body": {"prompt": "hi"}})
        assert envelope.request_id == envelope.body.request_id == "env-1"

    def test_a_flat_payload_keeps_the_client_id(self):
        envelope = BaseRequest.from_payload({"request_id": "client-1", "prompt": "hi"})
        assert envelope.request_id == envelope.body.request_id == "client-1"

    def test_an_id_is_minted_once_for_both(self):
        envelope = BaseRequest.from_payload({"prompt": "hi"})
        assert envelope.request_id and envelope.body.request_id == envelope.request_id

    def test_a_bare_run_request_keeps_its_own_id(self):
        envelope = BaseRequest.from_payload(BaseRunRequest(prompt="hi", request_id="body-1"))
        assert envelope.request_id == envelope.body.request_id == "body-1"

    def test_a_bare_run_request_without_an_id_gets_the_envelope_id(self):
        envelope = BaseRequest.from_payload(BaseRunRequest(prompt="hi"))
        assert envelope.request_id and envelope.body.request_id == envelope.request_id

    def test_a_prebuilt_envelope_hands_its_id_to_the_body(self):
        envelope = BaseRequest.from_payload(BaseRequest(request_id="env-1", body=BaseRunRequest(prompt="hi")))
        assert envelope.body.request_id == "env-1"


class TestRuntimePublication:
    @pytest.mark.asyncio
    async def test_run_publishes_the_given_id(self, runtime, agent):
        session = runtime.sessions().new("s1")
        await runtime.run(agent, session, _REQUESTS, request_id="req-1")
        assert agent.runner.seen == ["req-1"]
        assert session.get_request_id() is None

    @pytest.mark.asyncio
    async def test_stream_publishes_the_given_id(self, runtime, agent):
        session = runtime.sessions().new("s1")
        _ = [chunk async for chunk in runtime.stream(agent, session, _REQUESTS, request_id="req-1")]
        assert agent.runner.seen == ["req-1"]
        assert session.get_request_id() is None

    @pytest.mark.asyncio
    async def test_an_id_is_minted_per_run_when_absent(self, runtime, agent):
        await runtime.run(agent, runtime.sessions().new("s1"), _REQUESTS)
        _ = [chunk async for chunk in runtime.stream(agent, runtime.sessions().new("s2"), _REQUESTS)]
        first, second = agent.runner.seen
        assert re.fullmatch(r"[0-9a-f]{32}", first) and re.fullmatch(r"[0-9a-f]{32}", second)
        assert first != second


class TestChatServiceThreading:
    @pytest.mark.asyncio
    async def test_the_request_id_reaches_the_run(self, runtime, agent, monkeypatch):
        service = AgentService()
        service._runtime, service._agent, service._session = runtime, agent, runtime.sessions().new("s1")
        handler = AgentHandler()
        handler.service = service
        monkeypatch.setattr(ChatService, "prepare_agent_handler", lambda self, session_id, agent_name: handler)

        await ChatService().execute(BaseRunRequest(prompt="hi", session_id="s1", request_id="abc"))

        assert agent.runner.seen == ["abc"]
