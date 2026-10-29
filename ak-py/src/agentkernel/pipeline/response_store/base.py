import logging
import time
from abc import ABC, abstractmethod
from typing import Dict, Iterator, List, Optional

from ...core.config import AKConfig


class ResponseStore(ABC):
    """
    Abstract base class for response message storage systems.
    """

    _log = logging.getLogger("ak.pipeline.response_store")

    @abstractmethod
    def add_message(self, message: Dict) -> None:
        """
        Store a response message.

        :param message: message containing request_id, session_id, status_code, body
        :return: None
        """
        pass

    @abstractmethod
    def get_message(self, request_id: str, get_and_delete: bool = False) -> Dict | None:
        """
        Retrieve a specific message's body by its request ID.

        :param request_id: Request ID
        :param get_and_delete: Delete the message after retrieval when True
        :return: the stored record's ``body`` as dict or None if not found
        """
        pass

    @abstractmethod
    def get_record(self, request_id: str, get_and_delete: bool = False) -> Dict | None:
        """
        Retrieve the full stored record by its request ID.

        Unlike :meth:`get_message`, this returns the whole record given to :meth:`add_message`
        (``session_id``/``request_id``/``status_code``/``body``). The pipeline REST surface
        reads records so it can honor the stored ``status_code``.

        :param request_id: Request ID
        :param get_and_delete: Delete the record after retrieval when True
        :return: the stored record as dict or None if not found
        """
        pass

    @property
    def shared(self) -> bool:
        """Whether a process other than the writer can read what this store holds.

        Distinct from ``supports_chunk_streaming``: that says the store *can* carry a stream,
        this says a second process can *read* it. A topology that runs the agent in another
        process needs both, and the in-memory store answers True to the first while failing
        this one. Defaults True because every backend but that one is an external service;
        a bring-your-own store overrides it when its state lives in the writing process.
        """
        return True

    # -- optional chunk-streaming capability (local SSE delivery) ---------------------------

    def supports_chunk_streaming(self) -> bool:
        """Whether this store can buffer and stream per-request chunks (the local SSE path).

        The pipeline checks this capability instead of concrete store types, so a
        bring-your-own store can take part in STREAM delivery by implementing
        ``add_chunk``/``stream``/``close_stream`` and returning True here.
        """
        return False

    @staticmethod
    def _chunk_timeout(chunk_timeout: Optional[float] = None) -> float:
        """Resolve how long ``stream`` waits for each next chunk.

        Shared by every chunk-streaming store so the budget cannot drift between them. An
        explicit value wins; otherwise the response store's own ``retry_count * delay`` is
        reused rather than introducing a second knob for the same wait.

        :param chunk_timeout: Caller-supplied budget, or None to derive one.
        :return: Seconds to wait for each chunk.
        """
        if chunk_timeout is not None:
            return chunk_timeout
        response_store_config = AKConfig.get().execution.response_store
        if response_store_config is not None:
            return response_store_config.retry_count * response_store_config.delay
        return 60.0  # matches the request handler's default local wait budget (60 x 1s)

    def add_chunk(self, request_id: str, chunk: Dict) -> None:
        """Append one streaming chunk for a request. Chunk-streaming stores only."""
        raise NotImplementedError(f"{type(self).__name__} does not support chunk streaming")

    def stream(self, request_id: str, chunk_timeout: Optional[float] = None) -> Iterator[Dict]:
        """Yield a request's chunks in order until its done chunk. Chunk-streaming stores only."""
        raise NotImplementedError(f"{type(self).__name__} does not support chunk streaming")

    def close_stream(self, request_id: str) -> None:
        """Release a request's chunk state, unblocking any pending reader. Chunk-streaming stores only."""
        raise NotImplementedError(f"{type(self).__name__} does not support chunk streaming")

    # -- optional key-scan capability (the sandbox broker's idle-sweep inventory, #503) ------

    def supports_key_scan(self) -> bool:
        """Whether this store can enumerate stored records by request-id prefix.

        The pipeline checks this capability instead of concrete store types (the
        chunk-streaming precedent above); a bring-your-own store opts in by implementing
        ``scan_records`` and returning True here. The sandbox broker worker disables its
        idle-session sweep, with a warning, on a store without it.
        """
        return False

    def scan_records(self, prefix: str) -> List[Dict]:
        """Return every stored record whose request_id starts with ``prefix``. Scan-capable stores only."""
        raise NotImplementedError(f"{type(self).__name__} does not support key scans")

    def get_record_with_retry(self, request_id: str, get_and_delete: bool = False) -> Dict | None:
        """
        Wait until a record exists for a request ID and retrieve the whole record.

        Polls the full record (:meth:`get_record`) rather than the body alone, so callers can
        honor the stored ``status_code``; read ``record["body"]`` for the message itself.

        :param request_id: Request ID
        :param get_and_delete: Delete the record after retrieval when True
        :return: the stored record as dict or None if not found
        """
        retry_count, delay = self._get_retry_config()
        for attempt in range(retry_count):
            self._log.debug("Attempt %d/%d for request_id=%s", attempt + 1, retry_count, request_id)
            record = self.get_record(request_id, get_and_delete)
            if record is not None:
                return record
            if attempt < retry_count - 1:
                time.sleep(delay)
        return None

    @staticmethod
    def _get_retry_config() -> tuple[int, float]:
        """Read (retry_count, delay) for get_record_with_retry from config.

        Falls back to _ResponseStoreConfig's defaults when no execution.response_store block is
        configured (possible on the pipeline's local default path) instead of raising.
        """
        response_store_config = AKConfig.get().execution.response_store
        if response_store_config is None:
            return 5, 5.0  # matches _ResponseStoreConfig's field defaults
        return response_store_config.retry_count, response_store_config.delay

    @abstractmethod
    def delete_message(self, request_id: str) -> None:
        """
        Delete a specific message.

        :param request_id: Request ID
        :return: None
        """
        pass
