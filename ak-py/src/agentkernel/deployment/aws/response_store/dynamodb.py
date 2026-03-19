import boto3

from ...common.response_store import ResponseStore


class DynamoDBResponseStore(ResponseStore):

    def __init__(self, table_name: str, region: str):
        dynamodb = boto3.resource("dynamodb", region_name=region)

        self.table = dynamodb.Table(table_name)

    def add_message(self, message: dict) -> None:
        self.table.put_item(Item=message)

    def get_messages(self, session_id: str) -> list[dict]:
        response = self.table.query(
            KeyConditionExpression="session_id = :sid",
            ExpressionAttributeValues={":sid": session_id}
        )

        return response.get("Items", [])

    def delete_message(self, session_id: str, message_id: str) -> None:
        self.table.delete_item(
            Key={
                "session_id": session_id,
                "message_id": message_id
            }
        )

    def delete_session(self, session_id: str) -> None:
        response = self.table.query(
            KeyConditionExpression="session_id = :sid",
            ExpressionAttributeValues={":sid": session_id}
        )

        with self.table.batch_writer() as batch:
            for item in response.get("Items", []):
                batch.delete_item(
                    Key={
                        "session_id": item["session_id"],
                        "message_id": item["message_id"]
                    }
                )
