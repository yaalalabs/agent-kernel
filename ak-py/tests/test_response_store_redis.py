"""RedisResponseStore specifics the shared contract does not cover: key layout, TTL and the
close sentinel. The behavioural conformance lives in test_response_store_contract.py.

There was no redis response-store test before #710 — only valkey — so this also covers the
record path the chunk work builds on.
"""

import json

import pytest

from agentkernel.core.util.driver import redis as redis_driver_module
from agentkernel.pipeline.response_store.redis import _CLOSE_SENTINEL, RedisResponseStore


class FakeRedisClient:
    """Minimal stand-in: these tests inspect key layout, so a non-blocking pop is enough.

    The blocking behaviour is covered by the contract suite, which uses a condition-backed fake.
    """

    def __init__(self):
        self.store: dict[str, str] = {}
        self.lists: dict[str, list[str]] = {}
        self.expires: dict[str, int] = {}

    def ping(self):
        return True

    def set(self, key, value, ex=None, nx=False):
        self.store[key] = value
        return True

    def get(self, key):
        return self.store.get(key)

    def delete(self, *keys):
        for key in keys:
            self.store.pop(key, None)
            self.lists.pop(key, None)

    def rpush(self, key, value):
        self.lists.setdefault(key, []).append(value)

    def blpop(self, keys, timeout=0):
        key = keys[0]
        if not self.lists.get(key):
            return None
        return (key, self.lists[key].pop(0))

    def expire(self, name, time):  # noqa: A002 — the client's own parameter name
        self.expires[name] = time


@pytest.fixture
def client(monkeypatch):
    fake = FakeRedisClient()
    monkeypatch.setattr(redis_driver_module.redis, "from_url", lambda *a, **k: fake)
    return fake


def _store(ttl: int = 0) -> RedisResponseStore:
    return RedisResponseStore(url="redis://localhost:6379", prefix="ak:resp:", ttl=ttl)


def test_chunks_use_a_key_separate_from_the_record(client):
    """A chunk stream must not collide with the request's stored record."""
    store = _store()
    store.add_message({"request_id": "r1", "session_id": "s1", "body": {"text": "hi"}})
    store.add_chunk("r1", {"delta": "a"})

    assert "ak:resp:r1" in client.store, "the record key"
    assert "ak:resp:chunks:r1" in client.lists, "the chunk key"
    assert store.get_record("r1") == {"request_id": "r1", "session_id": "s1", "body": {"text": "hi"}}


def test_each_chunk_refreshes_the_ttl(client):
    """A long run must not have its chunk list expire mid-stream."""
    store = _store(ttl=120)
    store.add_chunk("r1", {"delta": "a"})
    assert client.expires["ak:resp:chunks:r1"] == 120

    client.expires.clear()
    store.add_chunk("r1", {"delta": "b"})
    assert client.expires["ak:resp:chunks:r1"] == 120


def test_no_ttl_is_applied_when_the_driver_has_none(client):
    store = _store(ttl=0)
    store.add_chunk("r1", {"delta": "a"})
    assert client.expires == {}


def test_the_sentinel_ends_the_stream_without_being_yielded(client):
    """close_stream's marker releases the reader; it must never surface as a chunk."""
    store = _store()
    store.add_chunk("r1", {"delta": "a"})
    store.close_stream("r1")

    received = list(store.stream("r1", chunk_timeout=5))
    assert received == [{"delta": "a"}]
    assert _CLOSE_SENTINEL not in [json.dumps(chunk) for chunk in received]


def test_the_chunk_key_is_dropped_when_the_stream_ends(client):
    """The generator's finally releases state even though the reader stopped at `done`."""
    store = _store()
    store.add_chunk("r1", {"delta": "a"})
    store.add_chunk("r1", {"done": True})

    list(store.stream("r1", chunk_timeout=5))
    assert "ak:resp:chunks:r1" not in client.lists
