import json

from ...core.util.driver.valkey import ValkeyDriver
from .base import ResponseStore


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

    def delete_message(self, request_id: str) -> None:
        self._log.debug("Deleting Valkey response message for request_id=%s", request_id)
        self._driver.delete(self._driver.key(request_id))
