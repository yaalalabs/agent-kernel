"""PollerRunner: hosting a pull-based inbound adapter, and how it drains."""

import threading
from typing import Any, Dict, List

import pytest

from agentkernel.core.config import AKConfig
from agentkernel.core.model import AgentReply, AgentRequestText
from agentkernel.core.util.factory import AKConfigError
from agentkernel.integration.adapter.base import InboundParseResult, InboundRequest, OutboundAdapter, PollingInboundAdapter, Source
from agentkernel.integration.adapter.poller import PollerRunner
from agentkernel.integration.adapter.producer import IntegrationProducer
from agentkernel.integration.adapter.webhook import WebhookRESTRequestHandler
from agentkernel.pipeline.envelope import QueueName
from agentkernel.pipeline.thread_runner import ThreadRunner
from agentkernel.pipeline.transport.base import QueueTransportFactory
from agentkernel.pipeline.transport.in_memory import InMemoryTransport


class FakePollingAdapter(PollingInboundAdapter):
    name = "byo_pkg.FakeOutboundAdapter"
    poll_interval = 0.01

    def __init__(self, batches: List[List[str]] = None, fail_on_poll: bool = False):
        self._batches = batches if batches is not None else [["m1", "m2"]]
        self._fail_on_poll = fail_on_poll
        self.polls = 0
        self.handled: List[str] = []

    async def poll(self) -> List[Any]:
        self.polls += 1
        if self._fail_on_poll:
            raise RuntimeError("gmail unreachable")
        if not self._batches:
            return []
        return self._batches.pop(0)

    async def parse(self, raw: Any) -> InboundParseResult:
        return InboundParseResult(
            requests=[
                InboundRequest(
                    session_id=f"thread-{raw}",
                    request_id=raw,
                    requests=[AgentRequestText(prompt=raw)],
                    prompt=raw,
                    reply_context={"to": "alice@example.com"},
                )
            ]
        )

    def mark_handled(self, raw: Any) -> None:
        self.handled.append(raw)


class FakeOutboundAdapter(OutboundAdapter):
    name = "byo_pkg.FakeOutboundAdapter"

    async def deliver(self, reply: AgentReply, reply_context: Dict[str, str]) -> None:  # pragma: no cover
        raise AssertionError("a poller never delivers")

    async def deliver_error(self, message: str, reply_context: Dict[str, str]) -> None:  # pragma: no cover
        raise AssertionError("a poller never delivers")


@pytest.fixture(autouse=True)
def _environment(monkeypatch):
    monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")
    AKConfig._reset()
    InMemoryTransport.reset()
    ThreadRunner.shutdown_event.clear()
    yield
    ThreadRunner.shutdown_event.clear()
    InMemoryTransport.reset()
    AKConfig._reset()


def _runner(adapter, transport):
    return PollerRunner(adapter, producer=IntegrationProducer(transport))


def _drain(transport):
    return transport.create_consumer(QueueName.INPUT).fetch(10, 0.2)


class TestPolling:
    def test_a_poll_iteration_enqueues_every_event(self):
        transport = InMemoryTransport()
        adapter = FakePollingAdapter()
        assert _runner(adapter, transport).poll_once() == 2
        assert sorted(m.dedup_id for m in _drain(transport)) == ["m1", "m2"]

    def test_an_event_is_marked_handled_only_after_it_is_enqueued(self):
        adapter = FakePollingAdapter()
        _runner(adapter, InMemoryTransport()).poll_once()
        assert adapter.handled == ["m1", "m2"]

    def test_a_failing_poll_costs_one_iteration_not_the_process(self):
        adapter = FakePollingAdapter(fail_on_poll=True)
        assert _runner(adapter, InMemoryTransport()).poll_once() == 0

    def test_an_enqueue_failure_leaves_the_event_unmarked(self):
        class BrokenProducer(IntegrationProducer):
            def enqueue(self, adapter_name, request):
                raise RuntimeError("broker unreachable")

        adapter = FakePollingAdapter()
        assert PollerRunner(adapter, producer=BrokenProducer(InMemoryTransport())).poll_once() == 0
        assert adapter.handled == [], "an unenqueued event must be picked up again next iteration"


class TestLoop:
    def test_the_loop_stops_within_one_interval_of_the_shutdown_event(self):
        transport = InMemoryTransport()
        polled = threading.Event()

        class SignallingAdapter(FakePollingAdapter):
            # A long interval: the drain must not wait it out.
            poll_interval = 30.0

            async def poll(self):
                events = await super().poll()
                polled.set()
                return events

        adapter = SignallingAdapter(batches=[["m1"]])
        thread = threading.Thread(target=_runner(adapter, transport).start, kwargs={"exit_on_shutdown": False}, daemon=True)
        thread.start()
        assert polled.wait(timeout=5), "the loop never polled"

        # The loop waits on the shutdown event rather than sleeping the interval, so a drain is
        # prompt even when an adapter polls every 30 s.
        ThreadRunner.shutdown_event.set()
        thread.join(timeout=5)
        assert not thread.is_alive()
        assert [m.dedup_id for m in _drain(transport)] == ["m1"]


class TestTopology:
    def test_run_rejects_the_in_memory_transport(self, monkeypatch):
        monkeypatch.setattr(QueueTransportFactory, "resolve_type", staticmethod(lambda: "in_memory"))
        with pytest.raises(AKConfigError) as excinfo:
            PollerRunner.run(FakePollingAdapter())
        assert "IOHandler" in str(excinfo.value)

    def test_a_webhook_adapter_cannot_be_hosted_here(self):
        adapter = FakePollingAdapter()
        adapter.source = Source.WEBHOOK
        with pytest.raises(ValueError, match="WebhookRESTRequestHandler"):
            PollerRunner(adapter)

    def test_a_polling_adapter_cannot_be_mounted_on_the_webhook_host(self):
        with pytest.raises(ValueError, match="PollerRunner"):
            WebhookRESTRequestHandler(FakePollingAdapter())
