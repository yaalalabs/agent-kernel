import time

import boto3

from ....common.response_store import ResponseStore


class DynamoDBResponseStore(ResponseStore):

    def __init__(self, table_name: str, region: str, ttl: int = 0):

        self._log.debug("Initializing DynamoDBResponseStore with table_name=%s region=%s ttl=%s", table_name, region, ttl)

        dynamodb = boto3.resource("dynamodb", region_name=region)

        self.table = dynamodb.Table(table_name)
        self.ttl = int(ttl)

    def add_message(self, message: dict) -> None:
        self._log.debug("Adding DynamoDB response message for request_id=%s", message.get("request_id"))
        if self.ttl > 0:
            message = dict(message)
            message["expiry_time"] = int(time.time()) + self.ttl
        self.table.put_item(Item=message)

    def get_message(self, request_id: str, get_and_delete: bool = False) -> dict | None:
        self._log.debug("Getting DynamoDB response message for request_id=%s get_and_delete=%s", request_id, get_and_delete)
        response = self.table.get_item(Key={"request_id": request_id})
        item = response.get("Item")
        if item is None:
            return None

        if get_and_delete:
            self.delete_message(request_id)
        return item["body"]

    def delete_message(self, request_id: str) -> None:
        self._log.debug("Deleting DynamoDB response message for request_id=%s", request_id)
        self.table.delete_item(Key={"request_id": request_id})
