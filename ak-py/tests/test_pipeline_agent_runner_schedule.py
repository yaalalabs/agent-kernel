"""Trigger consumption in the pipeline runners (#629 Phase 2).

A scheduled trigger carries its request metadata in the message body: EventBridge Scheduler
cannot set queue message attributes, and the local provider matches that one delivery contract.
Message attributes keep precedence, and a body-resolved request_id is injected back into the
attributes so the output side keeps forwarding it.
"""

import json
from unittest.mock import MagicMock

import pytest

from agentkernel.pipeline.agent_runner import AgentRunner, StreamAgentRunner
from agentkernel.pipeline.envelope import QueueMessage, QueueName
from agentkernel.pipeline.thread_runner import ThreadRunner
from agentkernel.pipeline.transport.base import QueueTransportFactory
from agentkernel.pipeline.transport.in_memory import InMemoryTransport


@pytest.fixture(autouse=True)
def _reset_state():
    InMemoryTransport.reset()
    ThreadRunner.shutdown_event.clear()
    yield
    InMemoryTransport.reset()
    ThreadRunner.shutdown_event.clear()


@pytest.fixture(autouse=True)
def _in_memory_transport(monkeypatch):
    """StreamAgentRunner only relaxes its endpoint_url requirement on the in_memory transport."""
    monkeypatch.setattr(QueueTransportFactory, "resolve_type", staticmethod(lambda: "in_memory"))


def _trigger_message(attributes=None, **body_extras) -> QueueMessage:
    """An input message whose body carries the trigger metadata, as a schedule provider sends it."""
    body = {"prompt": "run the weekly report", "session_id": "s1", "agent": None, **body_extras}
    return QueueMessage(
        body=json.dumps(body),
        attributes=attributes if attributes is not None else {},
        group_id="s1",
        dedup_id="d1",
        message_id="m1",
    )


def _fetch_output(transport, n=10):
    return transport.create_consumer(QueueName.OUTPUT).fetch(n, 0.5)


def _runner(transport, status_code=200):
    chat_service = MagicMock()
    chat_service.process_chat_request.return_value = (status_code, {"result": "done", "session_id": "s1"})
    return AgentRunner(transport=transport, chat_service=chat_service)


class TestAgentRunnerBodyFallback:
    def test_body_request_id_is_resolved_and_forwarded_to_the_output(self):
        transport = InMemoryTransport()

        _runner(transport).process(_trigger_message(request_id="sched-run-1", user_id="u1"))

        [out] = _fetch_output(transport)
        assert out.attributes["request_id"] == "sched-run-1"
        assert out.attributes["user_id"] == "u1"

    def test_body_metadata_is_injected_into_the_input_message(self):
        """ResponseHandler._store_response reads request_id from the attributes, so the resolved
        value has to land there and not just in the log line."""
        message = _trigger_message(request_id="sched-run-1", user_id="u1")

        _runner(InMemoryTransport()).process(message)

        assert message.attributes["request_id"] == "sched-run-1"
        assert message.attributes["user_id"] == "u1"

    def test_attribute_takes_precedence_over_the_body(self):
        transport = InMemoryTransport()
        message = _trigger_message(attributes={"request_id": "from-attribute"}, request_id="from-body")

        _runner(transport).process(message)

        [out] = _fetch_output(transport)
        assert out.attributes["request_id"] == "from-attribute"

    def test_body_user_id_does_not_override_an_existing_attribute(self):
        transport = InMemoryTransport()
        message = _trigger_message(attributes={"user_id": "from-attribute"}, request_id="sched-run-1", user_id="from-body")

        _runner(transport).process(message)

        [out] = _fetch_output(transport)
        assert out.attributes["user_id"] == "from-attribute"

    def test_missing_in_both_attributes_and_body_still_raises(self):
        runner = _runner(InMemoryTransport())
        with pytest.raises(ValueError, match="attributes or body"):
            runner.process(_trigger_message())


class TestStreamAgentRunnerBodyFallback:
    def test_body_request_id_is_resolved_for_streamed_triggers(self):
        transport = InMemoryTransport()
        chat_service = MagicMock()
        chat_service.process_stream_chat_sync.return_value = iter([json.dumps({"done": True, "session_id": "s1"})])

        StreamAgentRunner(transport=transport, chat_service=chat_service).process(_trigger_message(request_id="sched-run-1", user_id="u1"))

        [out] = _fetch_output(transport)
        assert out.attributes["request_id"] == "sched-run-1"
        assert out.attributes["user_id"] == "u1"

    def test_missing_in_both_attributes_and_body_still_raises(self):
        runner = StreamAgentRunner(transport=InMemoryTransport(), chat_service=MagicMock())
        with pytest.raises(ValueError, match="attributes or body"):
            runner.process(_trigger_message())
