import json
from typing import Iterator

from ...core.util.driver.valkey import ValkeyDriver
from .base import ResponseStore

# Pushed by close_stream to release a reader parked in BLPOP. A reserved string rather than a
# sentinel object, because the list holds JSON; it cannot collide with a chunk, which is always
# a JSON object.
_CLOSE_SENTINEL = "__ak_close__"


class ValkeyResponseStore(ResponseStore):

    def __init__(self, url: str, prefix: str = "ak:responses:", ttl: int = 0):

        self._log.debug("Initializing ValkeyResponseStore with prefix=%s ttl=%s", prefix, ttl)

        self._driver = ValkeyDriver(url=url, prefix=prefix, ttl=int(ttl), decode_responses=True)

    def add_message(self, message: dict) -> None:
        self._log.debug("Adding Valkey response message for request_id=%s", message.get("request_id"))
        request_id = message["request_id"]
        self._driver.set(self._driver.key(request_id), json.dumps(message))

    def get_message(self, request_id: str, get_and_delete: bool = False) -> dict | None:
        self._log.debug("Getting Valkey response message for request_id=%s get_and_delete=%s", request_id, get_and_delete)
        raw_message = self._driver.get(self._driver.key(request_id))
        if raw_message is None:
            return None
        message = json.loads(raw_message)
        if get_and_delete:
            self.delete_message(request_id)
        return message["body"]

    def get_record(self, request_id: str, get_and_delete: bool = False) -> dict | None:
        self._log.debug("Getting Valkey response record for request_id=%s get_and_delete=%s", request_id, get_and_delete)
        raw_message = self._driver.get(self._driver.key(request_id))
        if raw_message is None:
            return None
        message = json.loads(raw_message)
        if get_and_delete:
            self.delete_message(request_id)
        return message

    def delete_message(self, request_id: str) -> None:
        self._log.debug("Deleting Valkey response message for request_id=%s", request_id)
        self._driver.delete(self._driver.key(request_id))

    def supports_chunk_streaming(self) -> bool:
        return True

    def _chunk_key(self, request_id: str) -> str:
        return self._driver.key(f"chunks:{request_id}")

    def add_chunk(self, request_id: str, chunk: dict) -> None:
        """Append one streaming chunk for the request (consumed by ``stream``)."""
        key = self._chunk_key(request_id)
        self._driver.rpush(key, json.dumps(chunk))
        self._driver.expire(key)

    def stream(self, request_id: str, chunk_timeout: float | None = None) -> Iterator[dict]:
        """Yield the request's chunks in order until its done chunk.

        :param chunk_timeout: Max seconds to wait for each next chunk; defaults to the response
            store's ``retry_count * delay`` budget.
        :raises TimeoutError: When no chunk arrives within ``chunk_timeout``.
        """
        timeout = self._chunk_timeout(chunk_timeout)
        key = self._chunk_key(request_id)
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
            self._driver.delete(key)

    def close_stream(self, request_id: str) -> None:
        """Terminate a pending ``stream()`` for the request and drop its chunk state.

        Pushes the sentinel rather than deleting the key outright: a reader parked in ``blpop``
        on a worker thread is only released by something arriving on the list.
        """
        key = self._chunk_key(request_id)
        self._driver.rpush(key, _CLOSE_SENTINEL)
        self._driver.expire(key)

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
