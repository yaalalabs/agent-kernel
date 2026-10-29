"""The response-store contract against a REAL redis/valkey server (spec #710, integration CI).

`test_response_store_contract.py` runs the same contract against a fake whose `blpop` blocks on a
`threading.Condition`. That proves the store's own logic — the sentinel, the terminal chunk, the
timeout — but not the thing the whole design rests on: that a real `BLPOP` parks the connection
server-side and wakes the instant another *process* pushes. A fake cannot be wrong about that; a
server can.

Skipped unless the env var points at a reachable server, so the normal unit run is unaffected:

    docker compose -f examples/transport/nats/docker-compose.yaml up -d --wait valkey
    AK_TEST_VALKEY_URL=valkey://localhost:6379 uv run pytest tests/test_response_store_contract_live.py

Every test writes under a prefix unique to the run, so repeated runs and parallel jobs on a shared
server never read each other's chunks; the keys carry the store's TTL and die with the container.
"""

import os
import threading
import time
import uuid

import pytest

from agentkernel.pipeline.response_store.testing import ResponseStoreContract

REDIS_URL = os.getenv("AK_TEST_REDIS_URL")
VALKEY_URL = os.getenv("AK_TEST_VALKEY_URL")


def _prefix() -> str:
    """A prefix unique per store instance, so no two tests share a chunk list."""
    return f"ak:test:{uuid.uuid4().hex}:"


@pytest.mark.skipif(not REDIS_URL, reason="AK_TEST_REDIS_URL not set: the live store contract runs in integration CI")
class TestRedisResponseStoreContractLive(ResponseStoreContract):
    def make_store(self):
        from agentkernel.pipeline.response_store.redis import RedisResponseStore

        return RedisResponseStore(url=REDIS_URL, prefix=_prefix(), ttl=120)

    def test_blpop_wakes_on_a_write_from_another_connection(self):
        """The claim the fake cannot make: a parked reader is released by a real server push.

        Two stores means two connections, which is the shape that matters — the edge process and
        the agent runner never share one.
        """
        reader_store = self.make_store()
        writer_store = reader_store.__class__(url=REDIS_URL, prefix=reader_store._driver._prefix, ttl=120)
        received = []

        def read():
            received.extend(reader_store.stream("live-1", chunk_timeout=self.read_wait))

        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        time.sleep(0.5)
        assert received == [], "the reader did not park on the empty list"

        writer_store.add_chunk("live-1", {"delta": "from another connection"})
        writer_store.add_chunk("live-1", {"done": True})
        reader.join(timeout=self.read_wait)

        assert received == [{"delta": "from another connection"}, {"done": True}]


@pytest.mark.skipif(not VALKEY_URL, reason="AK_TEST_VALKEY_URL not set: the live store contract runs in integration CI")
class TestValkeyResponseStoreContractLive(ResponseStoreContract):
    def make_store(self):
        from agentkernel.pipeline.response_store.valkey import ValkeyResponseStore

        return ValkeyResponseStore(url=VALKEY_URL, prefix=_prefix(), ttl=120)

    def test_blpop_wakes_on_a_write_from_another_connection(self):
        """See the redis case: the cross-connection wake is the point of the live run."""
        reader_store = self.make_store()
        writer_store = reader_store.__class__(url=VALKEY_URL, prefix=reader_store._driver._prefix, ttl=120)
        received = []

        def read():
            received.extend(reader_store.stream("live-1", chunk_timeout=self.read_wait))

        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        time.sleep(0.5)
        assert received == [], "the reader did not park on the empty list"

        writer_store.add_chunk("live-1", {"delta": "from another connection"})
        writer_store.add_chunk("live-1", {"done": True})
        reader.join(timeout=self.read_wait)

        assert received == [{"delta": "from another connection"}, {"done": True}]
