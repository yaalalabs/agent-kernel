"""End to end over the in_memory transport: platform event -> agent -> platform reply.

This is the test that would have caught the whole point of #524 going wrong: the webhook answers
immediately, the agent runs on the other side of the queue, and the reply finds its way back to
the adapter that produced the request — with the reply context intact.
"""

import json
from typing import Any, Dict, List, Optional

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from agentkernel.core.base import Agent, Runner
from agentkernel.core.config import AKConfig
from agentkernel.core.model import AgentReply, AgentReplyText, AgentRequestText
from agentkernel.core.runtime import Runtime
from agentkernel.integration.adapter.base import InboundAdapter, InboundParseResult, InboundRequest, OutboundAdapter
from agentkernel.integration.adapter.factory import IntegrationAdapterFactory
from agentkernel.integration.adapter.producer import IntegrationProducer
from agentkernel.integration.adapter.webhook import WebhookRESTRequestHandler
from agentkernel.pipeline.agent_runner import AgentRunner
from agentkernel.pipeline.envelope import QueueName
from agentkernel.pipeline.response_handler import ResponseHandler
from agentkernel.pipeline.response_store.in_memory import InMemoryResponseStore
from agentkernel.pipeline.transport.in_memory import InMemoryTransport

AGENT_NAME = "roundtrip-agent"
ADAPTER_NAME = "byo_pkg.RoundTripOutboundAdapter"


class DummyRunner(Runner):
    async def run(self, agent, session, requests):
        prompt = requests[0].prompt if isinstance(requests[0], AgentRequestText) else ""
        if prompt == "boom":
            raise RuntimeError("agent exploded")
        return AgentReplyText(response=f"ok:{prompt}")

    async def stream(self, agent, session, requests):  # pragma: no cover - not exercised here
        raise NotImplementedError


class DummyAgent(Agent):
    def __init__(self):
        super().__init__(AGENT_NAME, DummyRunner("DummyRunner"))

    def get_description(self) -> str:
        return "Round-trip test agent"

    def get_a2a_card(self):
        return None

    def override_system_prompt(self, prompt):
        pass

    def attach_tool(self, tool):
        pass


class RoundTripOutboundAdapter(OutboundAdapter):
    """Stands in for a platform API, recording exactly what would have been sent."""

    name = ADAPTER_NAME
    delivered: List[tuple] = []
    errors: List[tuple] = []

    async def deliver(self, reply: AgentReply, reply_context: Dict[str, str]) -> None:
        RoundTripOutboundAdapter.delivered.append((str(reply), dict(reply_context)))

    async def deliver_error(self, message: str, reply_context: Dict[str, str]) -> None:
        RoundTripOutboundAdapter.errors.append((message, dict(reply_context)))

    async def acknowledge(self, reply_context: Dict[str, str]) -> Dict[str, str]:
        return {"ack_id": "ack-1"}


class RoundTripInboundAdapter(InboundAdapter):
    """Turns a toy webhook body into one request."""

    name = ADAPTER_NAME
    webhook_path = "/roundtrip/webhook"

    async def parse(self, raw: Request) -> InboundParseResult:
        body = await raw.json()
        prompt = body["text"]
        return InboundParseResult(
            requests=[
                InboundRequest(
                    session_id=body["conversation"],
                    request_id=body["id"],
                    requests=[AgentRequestText(prompt=prompt)],
                    prompt=prompt,
                    agent=AGENT_NAME,
                    user_id="u1",
                    reply_context={"channel": body["conversation"]},
                )
            ]
        )


@pytest.fixture(autouse=True)
def _environment(monkeypatch):
    monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")
    AKConfig._reset()
    InMemoryTransport.reset()
    InMemoryResponseStore.reset()
    RoundTripOutboundAdapter.delivered = []
    RoundTripOutboundAdapter.errors = []
    IntegrationAdapterFactory.reset()
    IntegrationAdapterFactory._cache[ADAPTER_NAME] = RoundTripOutboundAdapter()
    yield
    IntegrationAdapterFactory.reset()
    InMemoryResponseStore.reset()
    InMemoryTransport.reset()
    AKConfig._reset()


@pytest.fixture
def agent():
    agent = DummyAgent()
    Runtime.current().register(agent)
    yield agent
    Runtime.current().deregister(agent)


def _post(transport, text="hello", request_id="m1"):
    handler = WebhookRESTRequestHandler(RoundTripInboundAdapter(), producer=IntegrationProducer(transport))
    app = FastAPI()
    app.include_router(handler.get_router())
    return TestClient(app).post("/roundtrip/webhook", json={"id": request_id, "conversation": "C9", "text": text})


def _drain(transport, queue: QueueName):
    consumer = transport.create_consumer(queue)
    messages = consumer.fetch(10, 0.5)
    for message in messages:
        consumer.ack(message)
    return messages


def _run_pipeline(transport):
    """Move every queued message one hop: input -> agent runner -> output -> response handler."""
    runner = AgentRunner(transport=transport)
    for message in _drain(transport, QueueName.INPUT):
        runner.process(message)
    responder = ResponseHandler(transport=transport, response_store=InMemoryResponseStore())
    for message in _drain(transport, QueueName.OUTPUT):
        responder.process(message)


def test_a_platform_event_reaches_the_agent_and_the_reply_comes_back(agent):
    transport = InMemoryTransport()

    response = _post(transport)
    # The webhook answers before the agent has run at all.
    assert response.status_code == 200
    assert RoundTripOutboundAdapter.delivered == []

    _run_pipeline(transport)

    assert RoundTripOutboundAdapter.delivered == [("ok:hello", {"channel": "C9", "ack_id": "ack-1"})]


def test_the_edge_acknowledgement_reaches_the_delivery(agent):
    """The ack's return value is what carries, say, Slack's placeholder message id across."""
    transport = InMemoryTransport()
    _post(transport)
    _run_pipeline(transport)

    _, context = RoundTripOutboundAdapter.delivered[0]
    assert context["ack_id"] == "ack-1"


def test_a_failed_run_tells_the_user_instead_of_going_silent(agent):
    transport = InMemoryTransport()

    _post(transport, text="boom")
    _run_pipeline(transport)

    assert RoundTripOutboundAdapter.delivered == []
    [(message, context)] = RoundTripOutboundAdapter.errors
    assert message == RoundTripOutboundAdapter.ERROR_MESSAGE
    assert "exploded" not in message, "the raw error stays in the log"
    assert context["channel"] == "C9"


def test_a_platform_retry_does_not_run_the_agent_twice(agent):
    transport = InMemoryTransport()

    _post(transport, request_id="m1")
    _post(transport, request_id="m1")
    _run_pipeline(transport)

    assert len(RoundTripOutboundAdapter.delivered) == 1


def test_nothing_is_written_to_the_response_store(agent):
    """Integration traffic is delivered to its platform, not stored for a REST poller."""
    transport = InMemoryTransport()
    _post(transport)
    _run_pipeline(transport)

    assert InMemoryResponseStore().get_record("m1") is None


def test_the_queue_message_carries_no_raw_reply_address_in_its_body(agent):
    """Reply coordinates travel as attributes; in the body they would reach the agent as context."""
    transport = InMemoryTransport()
    _post(transport)

    [message] = transport.create_consumer(QueueName.INPUT).fetch(1, 0.5)
    body = json.loads(message.body)
    assert "reply_context" not in body
    assert message.attributes["reply_channel"] == "C9"
