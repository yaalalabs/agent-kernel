"""Client-library-agnostic response store shared by the Redis and Valkey backends.

The ``valkey`` client is a fork of ``redis-py`` with an identical API, so the two stores differ
only in which driver they construct. Keeping one body here is not only tidiness: the chunk-stream
lifecycle below is subtle enough that two copies would drift, which is exactly how the key leak
this module fixes came about (spec #710).

This module must not import ``redis`` or ``valkey``; the concrete subclasses supply the driver.
"""

import json
import threading
from typing import ClassVar, Iterator, Optional, Set

from ...core.util.driver.redis_like import _RedisLikeDriver
from .base import ResponseStore

# Pushed by close_stream to release a reader parked in BLPOP. A reserved string rather than a
# sentinel object, because the list holds JSON; it cannot collide with a chunk, which is always
# a JSON object.
_CLOSE_SENTINEL = "__ak_close__"

_CLOSE_MARKER_TTL_SECONDS = 60


class RedisLikeResponseStore(ResponseStore):
    """Response store over a Redis-compatible list/string backend.

    Records are plain JSON strings under ``<prefix><request_id>``; a streaming run's chunks are a
    separate list under ``<prefix>chunks:<request_id>``, drained with BLPOP so the reader parks on
    the server instead of polling.

    ``_live_streams`` holds the chunk keys that currently have a live ``stream()`` generator in
    this process, so ``close_stream`` can tell a reader that still needs waking from one that has
    already gone. Class-level for the same reason ``InMemoryResponseStore``'s state is:
    ``ResponseStoreFactory.create()`` hands back a fresh store per call, so two instances within
    one process must still agree on whether a reader exists. A reader in another process is
    invisible here, which is safe — ``close_stream`` is only ever called by the code that opened
    the stream.

    Subclasses construct ``self._driver`` and nothing else.
    """

    _live_streams: ClassVar[Set[str]] = set()
    _live_lock: ClassVar[threading.Lock] = threading.Lock()

    _driver: _RedisLikeDriver

    def add_message(self, message: dict) -> None:
        self._log.debug("Adding %s response message for request_id=%s", type(self).__name__, message.get("request_id"))
        self._driver.set(self._driver.key(message["request_id"]), json.dumps(message))

    def get_message(self, request_id: str, get_and_delete: bool = False) -> dict | None:
        record = self.get_record(request_id, get_and_delete)
        return None if record is None else record["body"]

    def get_record(self, request_id: str, get_and_delete: bool = False) -> dict | None:
        self._log.debug("Getting %s response record for request_id=%s get_and_delete=%s", type(self).__name__, request_id, get_and_delete)
        raw_message = self._driver.get(self._driver.key(request_id))
        if raw_message is None:
            return None
        message = json.loads(raw_message)
        if get_and_delete:
            self.delete_message(request_id)
        return message

    def delete_message(self, request_id: str) -> None:
        self._log.debug("Deleting %s response message for request_id=%s", type(self).__name__, request_id)
        self._driver.delete(self._driver.key(request_id))

    # -- chunk streaming --------------------------------------------------------------------

    def supports_chunk_streaming(self) -> bool:
        return True

    def _chunk_key(self, request_id: str) -> str:
        return self._driver.key(f"chunks:{request_id}")

    def add_chunk(self, request_id: str, chunk: dict) -> None:
        """Append one streaming chunk for the request (consumed by ``stream``)."""
        key = self._chunk_key(request_id)
        self._driver.rpush(key, json.dumps(chunk))
        self._driver.expire(key)

    def stream(self, request_id: str, chunk_timeout: Optional[float] = None) -> Iterator[dict]:
        """Yield the request's chunks in order until its done chunk.

        Registers the key as live for as long as this generator exists, so ``close_stream`` can
        tell a reader that still needs waking from one that has already gone. Deregistration
        happens **before** the key is deleted: the other order leaves a window in which a
        concurrent ``close_stream`` still sees a live reader and pushes a marker onto the key
        that was just removed, recreating it.

        :param chunk_timeout: Max seconds to wait for each next chunk; defaults to the response
            store's ``retry_count * delay`` budget.
        :raises TimeoutError: When no chunk arrives within ``chunk_timeout``.
        """
        timeout = self._chunk_timeout(chunk_timeout)
        key = self._chunk_key(request_id)
        with self._live_lock:
            self._live_streams.add(key)
        try:
            while True:
                raw = self._driver.blpop(key, timeout)
                if raw is None:
                    raise TimeoutError(f"No stream chunk received for request_id '{request_id}' within {timeout} s")
                if raw == _CLOSE_SENTINEL:
                    return
                chunk = json.loads(raw)
                yield chunk
                if chunk.get("done"):
                    return
        finally:
            with self._live_lock:
                self._live_streams.discard(key)
            self._driver.delete(key)

    def close_stream(self, request_id: str) -> None:
        """Terminate a pending ``stream()`` for the request and drop its chunk state.

        Two cases, and the difference matters. With a reader still live, the key must be *pushed*
        to: a thread parked in BLPOP is released only by something arriving on the list, and that
        reader's own ``finally`` then deletes the key. With no reader — the ordinary end of a run,
        where the generator already returned at the done chunk — a push would recreate the key it
        had just cleaned up and leave it behind for the whole record TTL, so the key is deleted
        instead. This mirrors ``InMemoryResponseStore.close_stream``, which pops the queue first
        and only signals when one was there.

        The pushed marker carries its own short TTL, because a reader suspended at ``yield``
        rather than parked in BLPOP never consumes it.
        """
        key = self._chunk_key(request_id)
        with self._live_lock:
            live = key in self._live_streams
        if not live:
            self._driver.delete(key)
            return
        self._driver.rpush(key, _CLOSE_SENTINEL)
        self._driver.expire_in(key, _CLOSE_MARKER_TTL_SECONDS)

    # -- key scan ---------------------------------------------------------------------------

    def supports_key_scan(self) -> bool:
        return True

    def scan_records(self, prefix: str) -> list[dict]:
        """SCAN keys under the driver prefix + ``prefix`` and return their parsed records."""
        records = []
        for key in self._driver.client.scan_iter(match=f"{self._driver.key(prefix)}*"):
            raw_message = self._driver.get(key)
            if raw_message is not None:
                records.append(json.loads(raw_message))
        return records
