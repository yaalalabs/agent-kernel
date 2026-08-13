import queue
import threading
from typing import Any, ClassVar, Dict, Generator, Optional

from ...core.config import AKConfig
from .base import ResponseStore


class InMemoryResponseStore(ResponseStore):
    """Process-wide in-memory response store for single-process/single-pod topologies (spec #495 §10).

    State is class-level (like InMemoryAttachmentStore / InMemoryThreadStore) so the request
    handler and the response handler share it across instances. ``get_message`` returns
    ``record["body"]``, matching the Redis/Valkey/DynamoDB stores' contract; ``get_record``
    additionally exposes the full record (``status_code`` included) for the pipeline request
    handler. ``add_chunk``/``stream`` carry STREAM-mode chunks to the local SSE generator.

    Not durable and not shared across processes: multi-process queue modes must use a shared
    backend (enforced at IOHandler startup). Records are expected to be consumed with
    ``get_and_delete=True``; unconsumed records live until process exit.
    """

    _lock: ClassVar[threading.Lock] = threading.Lock()
    _records: ClassVar[Dict[str, dict]] = {}
    _chunks: ClassVar[Dict[str, "queue.Queue[dict]"]] = {}

    def add_message(self, message: Dict) -> None:
        self._log.debug("Adding in-memory response message for request_id=%s", message.get("request_id"))
        with self._lock:
            self._records[message["request_id"]] = message

    def get_message(self, request_id: str, get_and_delete: bool = False) -> Dict | None:
        record = self.get_record(request_id, get_and_delete=get_and_delete)
        if record is None:
            return None
        return record["body"]

    def get_record(self, request_id: str, get_and_delete: bool = False) -> Optional[Dict[str, Any]]:
        """Return the full stored record (session_id, request_id, status_code, body), or None."""
        with self._lock:
            record = self._records.get(request_id)
            if record is not None and get_and_delete:
                del self._records[request_id]
            return record

    def delete_message(self, request_id: str) -> None:
        self._log.debug("Deleting in-memory response message for request_id=%s", request_id)
        with self._lock:
            self._records.pop(request_id, None)
            self._chunks.pop(request_id, None)

    def add_chunk(self, request_id: str, chunk: Dict[str, Any]) -> None:
        """Append one STREAM-mode chunk for the request (consumed by ``stream``)."""
        with self._lock:
            chunk_queue = self._chunks.setdefault(request_id, queue.Queue())
        chunk_queue.put(chunk)

    def stream(self, request_id: str, chunk_timeout: Optional[float] = None) -> Generator[Dict[str, Any], None, None]:
        """Yield the request's chunks in arrival order until a chunk with ``done`` is seen.

        :param chunk_timeout: Max seconds to wait for each next chunk; defaults to the response
            store's ``retry_count * delay`` budget.
        :raises TimeoutError: When no chunk arrives within ``chunk_timeout``.
        """
        if chunk_timeout is None:
            response_store_config = AKConfig.get().execution.response_store
            if response_store_config is not None:
                chunk_timeout = response_store_config.retry_count * response_store_config.delay
            else:
                chunk_timeout = 25.0
        with self._lock:
            chunk_queue = self._chunks.setdefault(request_id, queue.Queue())
        try:
            while True:
                try:
                    chunk = chunk_queue.get(timeout=chunk_timeout)
                except queue.Empty:
                    raise TimeoutError(f"No stream chunk received for request_id '{request_id}' within {chunk_timeout} s")
                yield chunk
                if chunk.get("done"):
                    return
        finally:
            with self._lock:
                self._chunks.pop(request_id, None)

    @classmethod
    def reset(cls) -> None:
        """Drop all process-wide state. Test isolation only."""
        with cls._lock:
            cls._records.clear()
            cls._chunks.clear()
