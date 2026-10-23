"""QueueRequestClient (#780 §1): the "enqueue, then wait for the whole reply" A2A and MCP share with REST."""

import json
import subprocess
import sys

import pytest

from agentkernel.core.config import AKConfig, _ResponseStoreConfig
from agentkernel.core.model import BaseRunRequest
from agentkernel.pipeline import request_client
from agentkernel.pipeline.envelope import ATTR_PROTOCOL, QueueName
from agentkernel.pipeline.request_client import QueuedReply, QueueRequestClient, ReplyTimeoutError
from agentkernel.pipeline.response_store.factory import ResponseStoreFactory
from agentkernel.pipeline.transport.base import QueueTransportFactory
from agentkernel.pipeline.transport.in_memory import InMemoryTransport


class FakeStore:
    """Answers ``get_record`` with None until read ``ready_after`` times, then with ``record``."""

    def __init__(self, record=None, ready_after: int = 0, events: list | None = None):
        self.record = record
        self.ready_after = ready_after
        self.reads: list[tuple[str, bool]] = []
        self.events = events if events is not None else []

    def get_record(self, request_id, get_and_delete=False):
        self.reads.append((request_id, get_and_delete))
        self.events.append("read")
        if self.record is not None and len(self.reads) > self.ready_after:
            return {"request_id": request_id, **self.record}
        return None


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch):
    monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")
    InMemoryTransport.reset()
    AKConfig._reset()
    yield
    InMemoryTransport.reset()
    AKConfig._reset()


@pytest.fixture
def sleeps(monkeypatch):
    """Record every sleep instead of sleeping."""
    recorded: list[float] = []

    async def _sleep(delay):
        recorded.append(delay)

    monkeypatch.setattr(request_client.asyncio, "sleep", _sleep)
    return recorded


def _body(**overrides) -> BaseRunRequest:
    return BaseRunRequest(**{"prompt": "hi", "session_id": "s1", "agent": "triage", **overrides})


def _client(store, transport=None, budget=(3, 0.5)) -> QueueRequestClient:
    return QueueRequestClient(transport=transport or InMemoryTransport(), response_store=store, budget=budget)


class TestEnvelope:
    @pytest.mark.asyncio
    async def test_the_message_is_the_rest_envelope_plus_the_protocol(self):
        transport = InMemoryTransport()
        store = FakeStore(record={"status_code": 200, "body": {"result": "ok"}})

        reply = await _client(store, transport).request(_body(), protocol="a2a")

        [message] = transport.create_consumer(QueueName.INPUT).fetch(1, 0.5)
        assert json.loads(message.body) == {"prompt": "hi", "session_id": "s1", "agent": "triage"}
        assert message.attributes == {"request_id": reply.request_id, ATTR_PROTOCOL: "a2a"}
        assert message.group_id == "s1"
        assert message.dedup_id == reply.request_id

    @pytest.mark.asyncio
    async def test_each_request_gets_a_fresh_request_id(self):
        store = FakeStore(record={"body": {"result": "ok"}})
        client = _client(store)

        first = await client.request(_body(), protocol="mcp")
        second = await client.request(_body(), protocol="mcp")

        assert first.request_id != second.request_id
        assert [request_id for request_id, _ in store.reads] == [first.request_id, second.request_id]


class TestValidation:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "overrides, protocol, message",
        [
            ({"session_id": None}, "a2a", "No session_id is provided in the request"),
            ({"session_id": ""}, "a2a", "No session_id is provided in the request"),
            ({"prompt": ""}, "a2a", "No prompt provided in the request"),
            ({}, "", "protocol is required"),
        ],
    )
    async def test_rejects_before_anything_is_sent(self, overrides, protocol, message):
        transport = InMemoryTransport()
        store = FakeStore(record={"body": {}})

        with pytest.raises(ValueError, match=message):
            await _client(store, transport).request(_body(**overrides), protocol=protocol)

        assert transport.create_consumer(QueueName.INPUT).fetch(1, 0.05) == []
        assert store.reads == []


class TestWait:
    @pytest.mark.asyncio
    async def test_the_first_read_comes_before_any_sleep(self, sleeps):
        store = FakeStore(record={"body": {"result": "ok"}})

        await _client(store).request(_body(), protocol="a2a")

        assert len(store.reads) == 1
        assert sleeps == []

    @pytest.mark.asyncio
    async def test_reads_until_the_record_is_there(self, sleeps):
        store = FakeStore(record={"body": {"result": "ok"}}, ready_after=2)

        reply = await _client(store, budget=(5, 0.25)).request(_body(), protocol="a2a")

        assert reply.result == "ok"
        assert len(store.reads) == 3
        assert sleeps == [0.25, 0.25]

    @pytest.mark.asyncio
    async def test_a_spent_budget_is_retry_count_reads_and_one_sleep_fewer(self, monkeypatch):
        events: list = []
        store = FakeStore(events=events)

        async def _sleep(delay):
            events.append(("sleep", delay))

        monkeypatch.setattr(request_client.asyncio, "sleep", _sleep)

        with pytest.raises(ReplyTimeoutError) as excinfo:
            await _client(store, budget=(3, 0.5)).request(_body(), protocol="mcp")

        assert events == ["read", ("sleep", 0.5), "read", ("sleep", 0.5), "read"]
        assert excinfo.value.request_id == store.reads[0][0]
        assert (excinfo.value.retry_count, excinfo.value.delay) == (3, 0.5)
        assert isinstance(excinfo.value, TimeoutError)

    @pytest.mark.asyncio
    async def test_every_read_deletes_the_record_it_returns(self, sleeps):
        store = FakeStore(record={"body": {}}, ready_after=1)

        await _client(store).request(_body(), protocol="a2a")

        assert all(get_and_delete is True for _, get_and_delete in store.reads)

    @pytest.mark.asyncio
    async def test_an_error_status_is_returned_not_raised(self):
        store = FakeStore(record={"status_code": 500, "body": {"error": "agent exploded"}})

        reply = await _client(store).request(_body(), protocol="a2a")

        assert reply.is_error
        assert reply.error == "agent exploded"

    @pytest.mark.asyncio
    async def test_transport_and_store_errors_reach_the_caller_unchanged(self):
        class BrokenStore:
            def get_record(self, request_id, get_and_delete=False):
                raise ConnectionError("store down")

        with pytest.raises(ConnectionError, match="store down"):
            await _client(BrokenStore()).request(_body(), protocol="a2a")


class TestBudget:
    def test_no_block_is_sixty_reads_one_second_apart(self):
        assert QueueRequestClient.budget_for(None) == (60, 1.0)

    def test_a_block_supplies_its_own_values(self):
        assert QueueRequestClient.budget_for(_ResponseStoreConfig()) == (5, 5)
        assert QueueRequestClient.budget_for(_ResponseStoreConfig(retry_count=3, delay=0.2)) == (3, 0.2)

    @pytest.mark.asyncio
    async def test_the_default_budget_is_read_from_config(self, monkeypatch, sleeps):
        monkeypatch.setenv("AK_EXECUTION__RESPONSE_STORE__RETRY_COUNT", "2")
        monkeypatch.setenv("AK_EXECUTION__RESPONSE_STORE__DELAY", "0.125")
        AKConfig._reset()
        store = FakeStore()

        with pytest.raises(ReplyTimeoutError):
            await QueueRequestClient(transport=InMemoryTransport(), response_store=store).request(_body(), protocol="a2a")

        assert len(store.reads) == 2
        assert sleeps == [0.125]


class TestConstruction:
    @pytest.mark.asyncio
    async def test_the_factories_build_what_is_not_injected(self, monkeypatch):
        transport = InMemoryTransport()
        store = FakeStore(record={"body": {"result": "ok"}})
        built = []

        def _build(made):
            def _create(*args, **kwargs):
                built.append(made)
                return made

            return _create

        monkeypatch.setattr(QueueTransportFactory, "create", _build(transport))
        monkeypatch.setattr(ResponseStoreFactory, "create", _build(store))
        client = QueueRequestClient()

        await client.request(_body(session_id="s1"), protocol="a2a")
        await client.request(_body(session_id="s2"), protocol="a2a")

        # Built once on first use, then reused.
        assert built == [transport, store]
        assert len(transport.create_consumer(QueueName.INPUT).fetch(10, 0.5)) == 2
        assert len(store.reads) == 2

    @pytest.mark.asyncio
    async def test_injected_dependencies_never_touch_config_or_factories(self, monkeypatch):
        def _refuse(*args, **kwargs):
            raise AssertionError("must not be called")

        monkeypatch.setattr(QueueTransportFactory, "create", _refuse)
        monkeypatch.setattr(ResponseStoreFactory, "create", _refuse)
        monkeypatch.setattr(request_client.AKConfig, "get", _refuse)
        store = FakeStore(record={"body": {"result": "ok"}})

        reply = await _client(store).request(_body(), protocol="a2a")

        assert reply.result == "ok"

    def test_the_module_never_imports_fastapi(self):
        code = "import sys, agentkernel.pipeline.request_client; sys.exit('fastapi' in sys.modules)"
        assert subprocess.run([sys.executable, "-c", code]).returncode == 0


class TestQueuedReply:
    def test_a_missing_status_counts_as_200(self):
        assert QueuedReply.from_record({"request_id": "r1", "body": {}}).status_code == 200
        assert QueuedReply.from_record({"request_id": "r1", "status_code": None, "body": {}}).status_code == 200

    @pytest.mark.parametrize("status_code, is_error", [(200, False), (202, False), (399, False), (400, True), (500, True)])
    def test_is_error_from_400(self, status_code, is_error):
        assert QueuedReply(request_id="r1", status_code=status_code).is_error is is_error

    def test_a_dict_body_exposes_its_fields(self):
        reply = QueuedReply.from_record(
            {"request_id": "r1", "status_code": "200", "body": {"result": {"a": 1}, "media_type": "application/json", "error": "e"}}
        )

        assert reply.request_id == "r1"
        assert reply.status_code == 200
        assert (reply.result, reply.media_type, reply.error) == ({"a": 1}, "application/json", "e")

    @pytest.mark.parametrize("body", [None, "text", ["a"]])
    def test_a_non_dict_body_exposes_nothing(self, body):
        reply = QueuedReply(request_id="r1", body=body)

        assert (reply.result, reply.media_type, reply.error) == (None, None, None)
        assert reply.body == body


class TestProtocolOf:
    @pytest.mark.parametrize(
        "attributes, expected",
        [
            ({ATTR_PROTOCOL: "a2a"}, "a2a"),
            ({ATTR_PROTOCOL: "mcp", "integration": "slack"}, "mcp"),
            ({ATTR_PROTOCOL: ""}, None),
            ({ATTR_PROTOCOL: object()}, None),
            ({ATTR_PROTOCOL: 1}, None),
            ({}, None),
        ],
    )
    def test_only_a_non_empty_str_counts(self, attributes, expected):
        assert QueueRequestClient.protocol_of(attributes) == expected
