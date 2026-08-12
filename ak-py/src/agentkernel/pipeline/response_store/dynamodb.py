from ...core.util.driver.dynamodb import DynamoDBDriver
from .base import ResponseStore


class DynamoDBResponseStore(ResponseStore):

    def __init__(self, table_name: str, region: str = None, ttl: int = 0):

        self._log.debug("Initializing DynamoDBResponseStore with table_name=%s region=%s ttl=%s", table_name, region, ttl)

        self._driver = DynamoDBDriver(table_name=table_name, partition_key="request_id", region=region, ttl=int(ttl))

    def add_message(self, message: dict) -> None:
        self._log.debug("Adding DynamoDB response message for request_id=%s", message.get("request_id"))
        self._driver.put(message)

    def get_message(self, request_id: str, get_and_delete: bool = False) -> dict | None:
        self._log.debug("Getting DynamoDB response message for request_id=%s get_and_delete=%s", request_id, get_and_delete)
        item = self._driver.get(request_id)
        if item is None:
            return None

        if get_and_delete:
            self.delete_message(request_id)
        return item["body"]

    def delete_message(self, request_id: str) -> None:
        self._log.debug("Deleting DynamoDB response message for request_id=%s", request_id)
        self._driver.delete(request_id)
