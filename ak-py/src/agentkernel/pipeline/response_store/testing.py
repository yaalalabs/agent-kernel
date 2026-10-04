"""Reusable conformance suite for chunk-streaming :class:`ResponseStore` implementations.

Mirrors ``pipeline/testing.py``'s ``QueueTransportContract``: subclass
:class:`ResponseStoreContract` in a test file, implement ``make_store()``, and pytest collects
the contract tests against that store. The contract pins the semantics a chunk stream depends on
— order, the terminal chunk, releasing a parked reader, a late reader, and the per-chunk timeout
— so the three implementations cannot drift from each other.

**``add_chunk`` is deliberately not required to be idempotent.** Duplicate delivery is a reader
concern, not a store one: the queue is at-least-once, and two attempts of the same
run produce genuinely different chunks that no write-level de-dup could reject. A bring-your-own
store must not inherit an obligation this design does not impose, so there is no de-dup case here.
"""

import threading
import time

import pytest

from .base import ResponseStore


class ResponseStoreContract:
    """Chunk-streaming conformance tests. Subclass per store and implement ``make_store``."""

    # Ceiling on a read that is expected to return. Generous: an in-process store returns as soon
    # as the chunk is there, so a high ceiling costs it nothing, while a real broker's first
    # blocking call also has to open a connection.
    read_wait: float = 10.0

    def make_store(self) -> ResponseStore:
        raise NotImplementedError

    def test_declares_both_capabilities_honestly(self):
        """A store in this suite streams chunks, and says whether another process can read it."""
        store = self.make_store()
        assert store.supports_chunk_streaming() is True
        assert isinstance(store.shared, bool)

    def test_chunks_arrive_in_order(self):
        store = self.make_store()
        for index in range(5):
            store.add_chunk("r-order", {"delta": str(index)})
        store.add_chunk("r-order", {"done": True})

        received = [chunk for chunk in store.stream("r-order", chunk_timeout=self.read_wait)]
        assert [chunk.get("delta") for chunk in received[:5]] == ["0", "1", "2", "3", "4"]

    def test_the_done_chunk_ends_the_stream(self):
        """The terminal chunk is yielded, and nothing after it is read."""
        store = self.make_store()
        store.add_chunk("r-done", {"delta": "a"})
        store.add_chunk("r-done", {"done": True})
        store.add_chunk("r-done", {"delta": "after the end"})

        received = list(store.stream("r-done", chunk_timeout=self.read_wait))
        assert received == [{"delta": "a"}, {"done": True}]

    def test_a_reader_waits_for_a_chunk_that_does_not_exist_yet(self):
        """The reader blocks rather than ending early — the whole point of the capability."""
        store = self.make_store()
        received = []

        def read():
            received.extend(store.stream("r-wait", chunk_timeout=self.read_wait))

        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        time.sleep(0.2)  # the reader is now parked on an empty stream
        assert received == [], "the reader returned before any chunk was written"

        store.add_chunk("r-wait", {"delta": "late"})
        store.add_chunk("r-wait", {"done": True})
        reader.join(timeout=self.read_wait)
        assert received == [{"delta": "late"}, {"done": True}]

    def test_close_stream_releases_a_parked_reader(self):
        """close_stream must unblock a reader mid-wait, not only drop state."""
        store = self.make_store()
        finished = threading.Event()

        def read():
            list(store.stream("r-close", chunk_timeout=self.read_wait))
            finished.set()

        threading.Thread(target=read, daemon=True).start()
        time.sleep(0.2)
        assert not finished.is_set()

        store.close_stream("r-close")
        assert finished.wait(timeout=self.read_wait), "close_stream left the reader parked"

    def test_a_reader_that_arrives_after_the_writer_still_sees_every_chunk(self):
        store = self.make_store()
        store.add_chunk("r-late", {"delta": "x"})
        store.add_chunk("r-late", {"done": True})

        received = list(store.stream("r-late", chunk_timeout=self.read_wait))
        assert received == [{"delta": "x"}, {"done": True}]

    def test_a_silent_stream_times_out(self):
        store = self.make_store()
        with pytest.raises(TimeoutError):
            list(store.stream("r-silent", chunk_timeout=0.2))

    def test_streams_are_isolated_by_request_id(self):
        store = self.make_store()
        store.add_chunk("r-one", {"delta": "one"})
        store.add_chunk("r-one", {"done": True})
        store.add_chunk("r-two", {"delta": "two"})
        store.add_chunk("r-two", {"done": True})

        assert list(store.stream("r-one", chunk_timeout=self.read_wait))[0] == {"delta": "one"}
        assert list(store.stream("r-two", chunk_timeout=self.read_wait))[0] == {"delta": "two"}
