import json
import redis

from ...common.response_store import ResponseStore


class RedisResponseStore(ResponseStore):

    def __init__(self, url: str, use_ssl: bool = False, prefix: str = "ak:responses:", ttl: int = 0):

        self.client = redis.Redis.from_url(url, decode_responses=True, ssl=use_ssl)
        self.prefix = prefix
        self.ttl = int(ttl)

    def _key(self, request_id: str) -> str:
        return f"{self.prefix}{request_id}"

    def add_message(self, message: dict) -> None:
        request_id = message["request_id"]
        key = self._key(request_id)
        self.client.set(key, json.dumps(message))
        if self.ttl > 0:
            self.client.expire(name=key, time=self.ttl)

    def get_message(self, request_id: str, get_and_delete: bool = False) -> dict | None:
        raw_message = self.client.get(self._key(request_id))
        if raw_message is None:
            return None
        message = json.loads(raw_message)
        if get_and_delete:
            self.delete_message(request_id)
        return message

    def delete_message(self, request_id: str) -> None:
        self.client.delete(self._key(request_id))