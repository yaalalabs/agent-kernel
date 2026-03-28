import json
import redis

from ...common.response_store import ResponseStore


class RedisResponseStore(ResponseStore):

    def __init__(self, host: str, port: int = 6379,
                 username: str | None = None,
                 password: str | None = None,
                 ssl: bool = True,
                 prefix: str = "ak:responses:"):

        self.client = redis.Redis(
            host=host,
            port=port,
            username=username,
            password=password,
            ssl=ssl,
            decode_responses=True,
        )
        self.prefix = prefix

    def _key(self, session_id: str) -> str:
        return f"{self.prefix}{session_id}"

    def add_message(self, message: dict) -> None:
        session_id = message["session_id"]
        self.client.rpush(self._key(session_id), json.dumps(message))

    def get_messages(self, session_id: str) -> list[dict]:
        messages = self.client.lrange(self._key(session_id), 0, -1) # 0 to -1 means all items

        return [json.loads(m) for m in messages]

    def delete_message(self, session_id: str, message_id: str) -> None:
        key = self._key(session_id)

        messages = self.client.lrange(key, 0, -1)

        for m in messages:
            parsed = json.loads(m)

            if parsed["message_id"] == message_id:
                self.client.lrem(key, 0, m)
                break

    def delete_session(self, session_id: str) -> None:
        self.client.delete(self._key(session_id))
