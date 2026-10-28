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
from agentkernel.core.event import PausedInterruption
from agentkernel.core.model import AgentPausedReplyAny, AgentReply, AgentReplyText, AgentRequestText, AgentResumeRequestAny, ResumeDecision
from agentkernel.core.paused_run import PausedRunState
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
PAUSING_AGENT_NAME = "roundtrip-pausing-agent"
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


class PausingRunner(Runner):
    """Pauses on ``pause:<n>``, then answers once every interruption has a decision.

    Mirrors what the real adapters do either side of a decision: a partial resume clears the old
    record and writes a new one for what is left, so the remainder comes back as a second pause.
    """

    @property
    def supports_pause(self) -> bool:
        return True

    @staticmethod
    def _pause(agent, session, interruptions) -> AgentPausedReplyAny:
        record = PausedRunState.add(session, agent=agent.name, runner="PausingRunner", interruptions=interruptions, payload={})
        return AgentPausedReplyAny(run_id=record.id, session_id=session.id, agent=agent.name, interruptions=record.interruptions)

    async def run(self, agent, session, requests):
        prompt = requests[0].prompt if isinstance(requests[0], AgentRequestText) else ""
        count = int(prompt.removeprefix("pause:")) if prompt.startswith("pause:") else 1
        interruptions = [PausedInterruption(id=f"call_{n}", kind="tool_call", tool_name="refund_order") for n in range(1, count + 1)]
        return self._pause(agent, session, interruptions)

    async def resume(self, agent, session, requests, decisions, record):
        answered = {decision.id: decision for decision in decisions}
        remaining = [interruption for interruption in record.interruptions if interruption.id not in answered]
        PausedRunState.clear(session, record.id)
        session.get_non_volatile_cache().set(
            "applied", session.get_non_volatile_cache().get("applied", []) + [(d.id, d.status, d.message) for d in decisions]
        )
        if remaining:
            return self._pause(agent, session, remaining)
        return AgentReplyText(response="applied:" + ";".join(f"{i}={s}" for i, s, _ in session.get_non_volatile_cache().get("applied")))

    async def stream(self, agent, session, requests):  # pragma: no cover - not exercised here
        raise NotImplementedError


class PausingAgent(Agent):
    def __init__(self):
        super().__init__(PAUSING_AGENT_NAME, PausingRunner("PausingRunner"))

    def get_description(self) -> str:
        return "Round-trip pausing agent"

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
    paused: List[tuple] = []

    async def deliver(self, reply: AgentReply, reply_context: Dict[str, str]) -> None:
        RoundTripOutboundAdapter.delivered.append((str(reply), dict(reply_context)))

    async def deliver_paused(self, reply: AgentPausedReplyAny, reply_context: Dict[str, str]) -> None:
        RoundTripOutboundAdapter.paused.append(([i.id for i in reply.interruptions], dict(reply_context)))

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
        if "decision" in body:
            return InboundParseResult(requests=[self._decision(body)])
        prompt = body["text"]
        return InboundParseResult(
            requests=[
                InboundRequest(
                    session_id=body["conversation"],
                    request_id=body["id"],
                    requests=[AgentRequestText(prompt=prompt)],
                    prompt=prompt,
                    agent=body.get("agent", AGENT_NAME),
                    user_id="u1",
                    reply_context={"channel": body["conversation"]},
                )
            ]
        )

    @staticmethod
    def _decision(body: dict) -> InboundRequest:
        """A press, keyed the way both real adapters key one: by what was decided, not by the click."""
        interruption_id, status = body["decision"]
        conversation = body["conversation"]
        return InboundRequest(
            session_id=conversation,
            request_id=f"{ADAPTER_NAME}:{conversation}:{body['message']}:{interruption_id}:{status}",
            requests=[AgentResumeRequestAny(decisions=[ResumeDecision(id=interruption_id, status=status, message=body.get("reason"))])],
            agent=body.get("agent", PAUSING_AGENT_NAME),
            user_id=body.get("user", "u1"),
            reply_context={"channel": conversation},
        )


@pytest.fixture(autouse=True)
def _environment(monkeypatch):
    monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")
    AKConfig._reset()
    InMemoryTransport.reset()
    InMemoryResponseStore.reset()
    RoundTripOutboundAdapter.delivered = []
    RoundTripOutboundAdapter.errors = []
    RoundTripOutboundAdapter.paused = []
    IntegrationAdapterFactory.reset()
    IntegrationAdapterFactory._cache[ADAPTER_NAME] = RoundTripOutboundAdapter()
    # The session store is process-wide, so a resumed run's state would otherwise outlive its test.
    Runtime.current().sessions().clear()
    yield
    Runtime.current().sessions().clear()
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


@pytest.fixture
def pausing_agent():
    agent = PausingAgent()
    Runtime.current().register(agent)
    yield agent
    Runtime.current().deregister(agent)


def _press(transport, interruption_id, status="approved", message="812", request_id=None, **extra):
    """Post a button press through the same webhook the first turn arrived on."""
    handler = WebhookRESTRequestHandler(RoundTripInboundAdapter(), producer=IntegrationProducer(transport))
    app = FastAPI()
    app.include_router(handler.get_router())
    body = {"id": request_id or "ignored", "conversation": "C9", "message": message, "decision": [interruption_id, status], **extra}
    return TestClient(app).post("/roundtrip/webhook", json=body)


def _queued(transport) -> List[Any]:
    """Every input message, drained one at a time.

    The in_memory transport keeps at most one message in flight per group, and every press in a
    conversation shares one — so a single fetch sees one message however many were enqueued.
    """
    consumer = transport.create_consumer(QueueName.INPUT)
    messages: List[Any] = []
    while batch := consumer.fetch(1, 0.1):
        messages.extend(batch)
        for message in batch:
            consumer.ack(message)
    return messages


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


def _post(transport, text="hello", request_id="m1", agent=AGENT_NAME):
    handler = WebhookRESTRequestHandler(RoundTripInboundAdapter(), producer=IntegrationProducer(transport))
    app = FastAPI()
    app.include_router(handler.get_router())
    return TestClient(app).post("/roundtrip/webhook", json={"id": request_id, "conversation": "C9", "text": text, "agent": agent})


def test_a_pause_goes_out_a_press_comes_back_and_the_run_resumes(pausing_agent):
    """The whole point of #609, over a real transport: nothing in between knows it is a decision."""
    transport = InMemoryTransport()

    _post(transport, text="pause:1", agent=PAUSING_AGENT_NAME)
    _run_pipeline(transport)

    assert RoundTripOutboundAdapter.paused == [(["call_1"], {"channel": "C9", "ack_id": "ack-1"})]
    assert RoundTripOutboundAdapter.delivered == [], "a pause is not an ordinary reply"

    _press(transport, "call_1", "approved")
    _run_pipeline(transport)

    [(reply, context)] = RoundTripOutboundAdapter.delivered
    assert reply == "applied:call_1=approved"
    assert context["channel"] == "C9", "the resumed reply lands in the conversation that asked"


def test_a_denial_carries_its_reason_to_the_runner(pausing_agent):
    transport = InMemoryTransport()
    _post(transport, text="pause:1", agent=PAUSING_AGENT_NAME)
    _run_pipeline(transport)

    _press(transport, "call_1", "denied", reason="already refunded")
    _run_pipeline(transport)

    assert RoundTripOutboundAdapter.delivered == [("applied:call_1=denied", {"channel": "C9", "ack_id": "ack-1"})]


def test_the_same_button_pressed_twice_reaches_the_runtime_once(pausing_agent):
    """Both presses key the same, so the transport drops the second before any worker wakes."""
    transport = InMemoryTransport()
    _post(transport, text="pause:1", agent=PAUSING_AGENT_NAME)
    _run_pipeline(transport)

    _press(transport, "call_1", "approved")
    _press(transport, "call_1", "approved")

    assert len(_queued(transport)) == 1


def test_a_different_verb_or_interruption_is_a_different_decision(pausing_agent):
    transport = InMemoryTransport()
    _post(transport, text="pause:2", agent=PAUSING_AGENT_NAME)
    _run_pipeline(transport)

    _press(transport, "call_1", "approved")
    _press(transport, "call_1", "denied")
    _press(transport, "call_2", "approved")

    assert len(_queued(transport)) == 3, "only a repeat of one button deduplicates"


def test_answering_one_of_two_interruptions_brings_the_rest_back_as_a_fresh_pause(pausing_agent):
    transport = InMemoryTransport()
    _post(transport, text="pause:2", agent=PAUSING_AGENT_NAME)
    _run_pipeline(transport)

    assert RoundTripOutboundAdapter.paused == [(["call_1", "call_2"], {"channel": "C9", "ack_id": "ack-1"})]

    _press(transport, "call_1", "approved")
    _run_pipeline(transport)

    assert [ids for ids, _ in RoundTripOutboundAdapter.paused] == [["call_1", "call_2"], ["call_2"]]
    assert RoundTripOutboundAdapter.delivered == [], "the run is still waiting on the second decision"


def test_two_decisions_delivered_in_order_both_land(pausing_agent):
    """Deliberately sequential: the pipeline's per-session guarantee is not this issue's to assert."""
    transport = InMemoryTransport()
    _post(transport, text="pause:2", agent=PAUSING_AGENT_NAME)
    _run_pipeline(transport)

    _press(transport, "call_1", "approved")
    _run_pipeline(transport)
    _press(transport, "call_2", "denied", reason="not this one")
    _run_pipeline(transport)

    [(reply, _)] = RoundTripOutboundAdapter.delivered
    assert reply == "applied:call_1=approved;call_2=denied", "neither decision overwrote the other"


def test_a_press_answering_a_resolved_pause_gets_the_generic_error(pausing_agent):
    transport = InMemoryTransport()
    _post(transport, text="pause:1", agent=PAUSING_AGENT_NAME)
    _run_pipeline(transport)
    _press(transport, "call_1", "approved")
    _run_pipeline(transport)

    _press(transport, "call_1", "denied", message="813")
    _run_pipeline(transport)

    [(error, context)] = RoundTripOutboundAdapter.errors
    assert error == RoundTripOutboundAdapter.ERROR_MESSAGE
    assert context["channel"] == "C9"
