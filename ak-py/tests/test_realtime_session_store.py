"""
A realtime call stores its session (#928) the way ``Runtime.stream`` does: once, when the call ends normally,
never after a failure. The write runs off the pool loop, which every call in the process shares.

This file keeps the real ``asyncio.to_thread`` (unlike ``test_realtime_pool.py``, which runs it inline), because
whether the store write runs off the loop is part of what is tested.
"""

import asyncio
import json
import logging
import threading

import pytest

from agentkernel import Agent, Runner, Session
from agentkernel.core.event import MessageEnd
from agentkernel.core.hooks import PostHook
from agentkernel.core.model import AgentReplyText, Principal
from agentkernel.core.realtime import RealtimeRunner
from agentkernel.core.runtime import Runtime
from agentkernel.core.session.in_memory import InMemorySessionStore
from agentkernel.pipeline.envelope import QueueName
from agentkernel.pipeline.realtime_pool import RealtimeConnection
from agentkernel.pipeline.transport.base import QueueTransportFactory
from agentkernel.pipeline.transport.in_memory import InMemoryTransport

HUMAN = Principal(subject="human", provider="realtime:livekit", namespace="lk-key")


class _Runner(Runner):
    def __init__(self):
        super().__init__("test-runner")

    async def run(self, agent, session, requests):
        return AgentReplyText(response="ok")

    async def stream(self, agent, session, requests):
        raise NotImplementedError()
        yield


class _Adapter(RealtimeRunner):
    disconnect_error: Exception | None = None

    def __init__(self):
        super().__init__("fake")

    async def connect(self, session, agent, callback):
        pass

    async def append_audio(self, base64_audio):
        pass

    async def send_text(self, text):
        pass

    async def disconnect(self):
        if _Adapter.disconnect_error is not None:
            raise _Adapter.disconnect_error


class _Agent(Agent):
    def __init__(self, name="general"):
        super().__init__(name, _Runner(), realtime_runner_cls=_Adapter)

    def get_description(self):
        return "fake"

    def get_a2a_card(self):
        return None

    def override_system_prompt(self, prompt):
        pass

    def attach_tool(self, tool):
        pass


class _RecordingStore(InMemorySessionStore):
    """Records every store: the thread it ran on, the session it got and the ``turn`` it held. Can block and fail."""

    def __init__(self):
        super().__init__()
        self.started = threading.Event()
        self.gate: threading.Event | None = None
        self.fail_times = 0
        self.stores: list[dict] = []

    def store(self, session):
        self.started.set()
        if self.gate is not None:
            self.gate.wait(5)
        if self.fail_times > 0:
            self.fail_times -= 1
            raise ConnectionError("store is down")
        self.stores.append(
            {
                "thread": threading.current_thread(),
                "session": session,
                "turn": session.get_non_volatile_cache().get("turn"),
                "marker": session.get_non_volatile_cache().get("marker"),
                "volatile": list(session.get_volatile_cache().keys()),
            }
        )
        super().store(session)


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    InMemoryTransport.reset()
    _Adapter.disconnect_error = None
    transport = InMemoryTransport()
    monkeypatch.setattr(QueueTransportFactory, "create", staticmethod(lambda *a, **k: transport))
    yield transport
    InMemoryTransport.reset()


@pytest.fixture
def store():
    return _RecordingStore()


def _connection(store, agent=None):
    return RealtimeConnection("s1", agent or _Agent(), Runtime(store), Session("s1"), asyncio.get_running_loop())


async def _until(predicate, timeout=3.0):
    for _ in range(int(timeout / 0.01)):
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition not reached in time")


def _drain(transport):
    consumer = transport.create_consumer(QueueName.OUTPUT)
    kinds = []
    while True:
        messages = consumer.fetch(10, 0.1)
        if not messages:
            return kinds
        for message in messages:
            body = json.loads(message.body)
            kinds.append("done" if body.get("done") else body["event"]["type"])
            consumer.ack(message)


class TestCallEnd:
    @pytest.mark.asyncio
    async def test_a_normal_close_stores_the_final_state_off_the_loop(self, store):
        conn = _connection(store)
        await conn.connect()
        conn.session.get_non_volatile_cache().set("turn", 7)

        await conn.close()

        assert [s["turn"] for s in store.stores] == [7]
        assert store.stores[0]["session"] is conn.session  # the session itself, as Runtime.stream stores it
        assert store.stores[0]["thread"] is not threading.main_thread()

    @pytest.mark.asyncio
    async def test_a_turn_end_does_not_store(self, store):
        conn = _connection(store)
        await conn.connect()

        await conn.handle_framework_event("done", {"status": "completed"})
        await asyncio.sleep(0.2)

        assert store.stores == []
        await conn.close()
        assert len(store.stores) == 1

    @pytest.mark.asyncio
    async def test_the_volatile_cache_is_not_stored(self, store):
        conn = _connection(store)
        await conn.connect()
        conn.session.get_volatile_cache().set("hook-state", True)

        await conn.close()

        # As in Runtime.stream: stored before the run ends, then the run's end clears it on that same object.
        # Durable stores never write the volatile cache at all (get_all(volatile=False)).
        assert store.stores[0]["session"].get_volatile_cache().keys() == []

    @pytest.mark.asyncio
    async def test_a_post_hook_write_during_the_call_is_stored(self, store):
        class MarkTurnEnd(PostHook):
            async def on_run(self, session, requests, agent, agent_reply):
                return agent_reply

            async def on_stream_event(self, session, requests, agent, event):
                if isinstance(event, MessageEnd):
                    session.get_non_volatile_cache().set("marker", "turn-ended")
                return event

            def name(self):
                return "mark-turn-end"

        agent = _Agent()
        agent.post_hooks.append(MarkTurnEnd())
        conn = _connection(store, agent)
        await conn.connect()
        await conn.handle_framework_event("done", {"status": "completed"})
        await asyncio.sleep(0.2)

        await conn.close()

        assert store.stores[0]["marker"] == "turn-ended"

    @pytest.mark.asyncio
    async def test_the_store_is_attempted_when_the_native_session_fails_to_close(self, store):
        _Adapter.disconnect_error = RuntimeError("cannot close")
        conn = _connection(store)
        await conn.connect()
        conn.session.get_non_volatile_cache().set("turn", 3)

        with pytest.raises(RuntimeError, match="cannot close"):
            await conn.close()

        assert [s["turn"] for s in store.stores] == [3]

    @pytest.mark.asyncio
    async def test_a_second_close_stores_nothing_more(self, store):
        conn = _connection(store)
        await conn.connect()

        await conn.close()
        await conn.close()

        assert len(store.stores) == 1

    @pytest.mark.asyncio
    async def test_the_run_state_ends_with_the_call(self, store):
        conn = _connection(store)
        conn.publish_principal(HUMAN)
        await asyncio.sleep(0)
        await conn.connect()
        conn.session.get_volatile_cache().set("hook-state", 1)

        await conn.close()

        assert conn.session.get_principal() is None
        assert conn.session.get_volatile_cache().keys() == []

    @pytest.mark.asyncio
    async def test_a_failing_store_is_logged_and_the_run_still_ends(self, store, caplog):
        conn = _connection(store)
        conn.publish_principal(HUMAN)
        await asyncio.sleep(0)
        await conn.connect()
        store.fail_times = 1

        with caplog.at_level(logging.ERROR, logger="ak.pipeline.realtime_pool"):
            await conn.close()

        assert any("at the end of the call failed" in r.message for r in caplog.records)
        assert conn.session.get_principal() is None


class TestFailure:
    """A failed call is not stored, as ``Runtime.stream`` does not store a halted run."""

    @pytest.mark.asyncio
    async def test_a_native_error_stores_nothing(self, store):
        conn = _connection(store)
        await conn.connect()

        await conn.handle_framework_event("error", {"message": "native session failed"})
        await _until(lambda: conn._disconnecting)
        await asyncio.sleep(0.1)

        assert store.stores == []

    @pytest.mark.asyncio
    async def test_a_failed_connect_stores_nothing(self, store):
        conn = _connection(store)

        await conn.fail_to_connect(RuntimeError("could not start"))

        assert store.stores == []


class TestLoad:
    @pytest.mark.asyncio
    async def test_a_slow_store_at_one_close_does_not_block_another_calls_audio(self, store, _isolated):
        ending = _connection(store)
        talking = RealtimeConnection("s2", _Agent(), Runtime(InMemorySessionStore()), Session("s2"), asyncio.get_running_loop())
        await ending.connect()
        await talking.connect()
        _drain(_isolated)
        store.gate = threading.Event()

        closing = asyncio.create_task(ending.close())
        await _until(store.started.is_set)
        await talking.handle_framework_event("audio_delta", {"delta": "QUFB", "message_id": "m1"})
        await asyncio.sleep(0.2)
        emitted_while_storing = _drain(_isolated)
        still_blocked = not closing.done()
        store.gate.set()
        await closing

        assert "audio_delta" in emitted_while_storing
        assert still_blocked  # the other call's audio went out while this call's write had not finished
        await talking.close()


class _FakeValkeyClient:
    """Minimal in-memory stand-in for a valkey client (hash per key), as in ``test_sessions_valkey.py``."""

    def __init__(self):
        self.hashes: dict[str, dict[str, bytes]] = {}

    def ping(self):
        return True

    def hset(self, name, key, value):
        self.hashes.setdefault(name, {})[key] = value

    def hget(self, name, key):
        return self.hashes.get(name, {}).get(key)

    def hkeys(self, name):
        return [k.encode("utf-8") for k in self.hashes.get(name, {})]

    def exists(self, key):
        return 1 if key in self.hashes else 0

    def expire(self, name, time):
        pass

    def scan_iter(self, match=None, count=None):
        prefix = match[:-1] if match and match.endswith("*") else (match or "")
        return [k for k in self.hashes if k.startswith(prefix)]

    def delete(self, *keys):
        for k in keys:
            self.hashes.pop(k, None)


class TestDurableStoreRoundTrip:
    """What a call changed survives it on a real durable store: the case the change exists for."""

    @pytest.mark.asyncio
    async def test_a_call_on_valkey_leaves_its_owner_and_hook_state_for_the_next_load(self, monkeypatch):
        import valkey

        from agentkernel.core.session.valkey import ValkeySessionStore
        from agentkernel.core.util.driver import valkey as valkey_driver_module

        class Cfg:
            class session:
                type = "valkey"
                cache = None

                class valkey:
                    url = "valkey://localhost:6379"
                    prefix = "ak:test:"
                    ttl = 60

        client = _FakeValkeyClient()
        monkeypatch.setattr(valkey_driver_module.valkey, "from_url", lambda *a, **k: client)
        assert valkey  # the extra is installed in the test environment

        def build_store():
            # Only the store's construction reads the config (drivers take explicit parameters), so it is
            # stubbed just here and the connection keeps the real config it needs for the rest.
            with monkeypatch.context() as patch:
                patch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: Cfg))
                return ValkeySessionStore()

        sessions = build_store()
        session = sessions.new("s1")
        conn = RealtimeConnection("s1", _Agent(), Runtime(sessions), session, asyncio.get_running_loop())
        conn.publish_principal(HUMAN)
        await asyncio.sleep(0)
        await conn.connect()
        session.get_non_volatile_cache().set("turn", 4)
        await conn.close()

        reloaded = build_store().load("s1", strict=True)  # a fresh store, as another pod would have
        assert reloaded.get_non_volatile_cache().get("turn") == 4
        assert reloaded.get_owner().subject == "human"
        assert reloaded.get_principal() is None
