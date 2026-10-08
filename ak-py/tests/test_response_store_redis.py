"""RedisResponseStore specifics the shared contract does not cover: key layout, TTL and the
close sentinel. The behavioural conformance lives in test_response_store_contract.py.

There was no redis response-store test before #710 — only valkey — so this also covers the
record path the chunk work builds on.
"""

import pytest
from test_response_store_contract import FakePipeline

from agentkernel.core.util.driver import redis as redis_driver_module
from agentkernel.pipeline.response_store.redis import RedisResponseStore
from agentkernel.pipeline.response_store.redis_like import _CLOSE_MARKER_TTL_SECONDS, _CLOSE_SENTINEL, RedisLikeResponseStore


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

    def pipeline(self):
        return FakePipeline(self)


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


def test_closing_a_stream_with_no_reader_drops_the_key_instead_of_signalling(client):
    """Nothing is parked, so a pushed marker would only resurrect the key (PR #755 review)."""
    store = _store(ttl=604800)
    store.add_chunk("r1", {"delta": "a"})

    store.close_stream("r1")

    assert "ak:resp:chunks:r1" not in client.lists
    assert _CLOSE_SENTINEL not in client.lists.get("ak:resp:chunks:r1", [])


def test_a_reader_finishing_during_close_stream_does_not_leave_the_key_behind(client):
    """The interleaving the deregister-before-delete ordering does not cover (PR #755 review).

    `close_stream` reads the registry and writes to the key as two steps. The SSE edges run the
    two halves on different threads — the generator on an executor worker via `asyncio.to_thread`,
    `close_stream` on the event loop — so a client disconnect can cancel the await while the
    worker is still parked in BLPOP, and the worker can then finish inside the gap.

    The fake's `rpush` stands in for that worker: it deregisters and deletes *just before* the push
    lands — after `close_stream` has already read `live=True`. That is the losing order, and
    without the recheck the push resurrects the key the reader had cleaned up.
    """
    store = _store(ttl=604800)
    key = "ak:resp:chunks:r1"
    store.add_chunk("r1", {"delta": "a"})
    RedisLikeResponseStore._live_streams.add(key)

    real_rpush = client.rpush

    def the_reader_finishes_then_our_push_lands(name, value):
        RedisLikeResponseStore._live_streams.discard(key)
        client.delete(key)
        real_rpush(name, value)

    client.rpush = the_reader_finishes_then_our_push_lands
    try:
        store.close_stream("r1")
    finally:
        RedisLikeResponseStore._live_streams.discard(key)

    assert key not in client.lists, "close_stream recreated the key the reader had just deleted"


def test_closing_a_live_stream_marks_the_key_with_its_own_short_ttl(client):
    """A reader suspended at `yield` never consumes the marker, so the marker must expire itself.

    Reading one chunk and stopping is what suspends the generator while leaving it registered live.

    The configured TTL is deliberately 0 here (keep forever) — the one case where inheriting the
    store's TTL would leave the key behind permanently.
    """
    store = _store(ttl=0)
    store.add_chunk("r1", {"delta": "a"})
    stream = store.stream("r1", chunk_timeout=5)
    assert next(stream) == {"delta": "a"}

    store.close_stream("r1")

    assert client.lists["ak:resp:chunks:r1"] == [_CLOSE_SENTINEL]
    assert client.expires["ak:resp:chunks:r1"] == _CLOSE_MARKER_TTL_SECONDS
    stream.close()


def test_the_chunk_key_is_dropped_when_the_stream_ends(client):
    """The generator's finally releases state even though the reader stopped at `done`."""
    store = _store()
    store.add_chunk("r1", {"delta": "a"})
    store.add_chunk("r1", {"done": True})

    list(store.stream("r1", chunk_timeout=5))
    assert "ak:resp:chunks:r1" not in client.lists
