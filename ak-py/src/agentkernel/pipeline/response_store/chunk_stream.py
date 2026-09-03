"""
Chunk streaming over a Redis-like list, shared by the Redis and Valkey response stores
(spec #524 §10.2).

The base :class:`~agentkernel.pipeline.response_store.base.ResponseStore` is a mailbox: one
finished record per ``request_id``, put and got. That is enough for a caller who waits for a whole
reply, and not enough for one who is streamed to — a stream is *n* frames, in order, delivered as
they are written, by a process that is not the one reading them.

This mixin adds that half for the two Redis-compatible backends. It is a list plus a blocking pop
rather than a Redis Stream because the contract is single-consumer, at-most-once and drop-on-close:
one reader (the request still holding the client's connection) drains one key until the run ends,
and nothing replays. Consumer groups would add machinery with nothing to show for it.

Every rule here mirrors :class:`~agentkernel.pipeline.response_store.in_memory.InMemoryResponseStore`
so both stores satisfy one contract test and a topology change never changes stream semantics.
"""

import json
from typing import Any, Dict, Generator, Optional

from ...core.config import AKConfig
from ...core.util.driver.redis_like import _RedisLikeDriver


class ChunkStreamMixin:
    """``add_chunk``/``stream``/``close_stream`` for a store whose driver speaks Redis.

    Mixed in ahead of :class:`ResponseStore` so these four methods win over the base's
    ``NotImplementedError`` defaults. Expects the host store to expose ``_driver``.
    """

    _driver: _RedisLikeDriver

    #: Pushed by :meth:`close_stream` to release a parked reader. A ``DEL`` cannot do it — a
    #: blocked ``BLPOP`` is waiting for an element, not watching the key.
    _CLOSE_SENTINEL: Dict[str, Any] = {"__ak_stream_closed__": True}

    #: Fallback wait budget when no ``execution.response_store`` block is configured; matches
    #: ``InMemoryResponseStore.stream``.
    _DEFAULT_CHUNK_TIMEOUT_SECONDS = 60.0

    def _chunk_key(self, request_id: str) -> str:
        """The list key holding one request's chunks, namespaced beside its record key.

        :param request_id: The request whose chunks are wanted.
        :return: The prefixed list key.
        """
        return self._driver.key(f"{request_id}:chunks")

    def supports_chunk_streaming(self) -> bool:
        """This store can carry a per-request chunk stream across processes."""
        return True

    def add_chunk(self, request_id: str, chunk: Dict[str, Any]) -> None:
        """Append one chunk for the request, releasing a reader parked on :meth:`stream`.

        :param request_id: The request the chunk belongs to.
        :param chunk: The chunk payload; serialized as JSON.
        """
        key = self._chunk_key(request_id)
        self._driver.rpush(key, json.dumps(chunk))
        # Re-applied per chunk rather than once: a stream that is abandoned mid-run must still
        # expire, and the key does not exist to be expired before its first chunk.
        self._driver.expire(key)

    def stream(self, request_id: str, chunk_timeout: Optional[float] = None) -> Generator[Dict[str, Any], None, None]:
        """Yield the request's chunks in arrival order until one carries ``done``.

        Blocking, not polling: each chunk is yielded as soon as it is written. The generator is
        synchronous, so an async caller must drive it off the event loop — see
        ``RequestHandler._sse_stream``, which runs each ``next()`` in a worker thread.

        :param request_id: The request to drain.
        :param chunk_timeout: Max seconds to wait for each next chunk; defaults to the response
            store's ``retry_count * delay`` budget.
        :return: Generator yielding chunk dicts.
        :raises TimeoutError: When no chunk arrives within ``chunk_timeout``.
        """
        if chunk_timeout is None:
            chunk_timeout = self._resolved_chunk_timeout()
        key = self._chunk_key(request_id)
        try:
            while True:
                raw = self._driver.blpop(key, chunk_timeout)
                if raw is None:
                    raise TimeoutError(f"No stream chunk received for request_id '{request_id}' within {chunk_timeout} s")
                chunk = json.loads(raw)
                if chunk == self._CLOSE_SENTINEL:
                    return
                yield chunk
                if chunk.get("done"):
                    return
        finally:
            # Deterministic release, including when the caller abandons the generator: an
            # abandoned key would otherwise sit until its TTL holding the tail of a dead run.
            self._driver.delete(key)

    def close_stream(self, request_id: str) -> None:
        """Terminate a pending :meth:`stream` for the request.

        Pushes the sentinel rather than deleting the key, because a reader blocked in ``BLPOP``
        is released by an element arriving, not by the key going away. The reader's own ``finally``
        then deletes the key.

        :param request_id: The request whose stream should end.
        """
        key = self._chunk_key(request_id)
        self._driver.rpush(key, json.dumps(self._CLOSE_SENTINEL))
        # TTL'd so an unread sentinel — nobody was streaming — does not linger forever.
        self._driver.expire(key)

    @classmethod
    def _resolved_chunk_timeout(cls) -> float:
        """The per-chunk wait budget from ``execution.response_store``, or the local default."""
        response_store_config = AKConfig.get().execution.response_store
        if response_store_config is None:
            return cls._DEFAULT_CHUNK_TIMEOUT_SECONDS
        return float(response_store_config.retry_count * response_store_config.delay)
