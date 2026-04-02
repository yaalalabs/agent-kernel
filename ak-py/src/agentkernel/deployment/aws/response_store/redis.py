import json
import redis

from ...common.response_store import ResponseStore


class RedisResponseStore(ResponseStore):

    def __init__(self, url: str, prefix: str = "ak:responses:", ttl: int = 0):

        self._log.debug("Initializing RedisResponseStore with prefix=%s ttl=%s", prefix, ttl)

        self.client = redis.Redis.from_url(url, decode_responses=True)
        self.prefix = prefix
        self.ttl = int(ttl)

    def _key(self, request_id: str) -> str:
        return f"{self.prefix}{request_id}"

    def add_message(self, message: dict) -> None:
        self._log.debug("Adding Redis response message for request_id=%s", message.get("request_id"))
        request_id = message["request_id"]
        key = self._key(request_id)
        self.client.set(key, json.dumps(message))
        if self.ttl > 0:
            self.client.expire(name=key, time=self.ttl)

    def get_message(self, request_id: str, get_and_delete: bool = False) -> dict | None:
        self._log.debug("Getting Redis response message for request_id=%s get_and_delete=%s", request_id, get_and_delete)
        raw_message = self.client.get(self._key(request_id))
        if raw_message is None:
            return None
        message = json.loads(raw_message)
        if get_and_delete:
            self.delete_message(request_id)
        return message['body']

    def delete_message(self, request_id: str) -> None:
        self._log.debug("Deleting Redis response message for request_id=%s", request_id)
        self.client.delete(self._key(request_id))