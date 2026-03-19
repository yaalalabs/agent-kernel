import json
import redis

from ...common.response_store import ResponseStore


class RedisResponseStore(ResponseStore):

    def __init__(self, host: str, port: int = 6379,
                 username: str | None = None,
                 password: str | None = None,
                 ssl: bool = True):

        self.client = redis.Redis(
            host=host,
            port=port,
            username=username,
            password=password,
            ssl=ssl,
            decode_responses=True,
        )

    def add_message(self, message: dict) -> None:
        session_id = message["session_id"]
        key = f"response:session:{session_id}" # TODO:: have to get from AKConfig prefix 
        self.client.rpush(key, json.dumps(message))

    def get_messages(self, session_id: str) -> list[dict]:
        key = f"response:session:{session_id}"

        messages = self.client.lrange(key, 0, -1) # 0 to -1 means all items

        return [json.loads(m) for m in messages]

    def delete_message(self, session_id: str, message_id: str) -> None:
        key = f"response:session:{session_id}"

        messages = self.client.lrange(key, 0, -1)

        for m in messages:
            parsed = json.loads(m)

            if parsed["message_id"] == message_id:
                self.client.lrem(key, 0, m)
                break

    def delete_session(self, session_id: str) -> None:
        key = f"response:session:{session_id}"

        self.client.delete(key)
