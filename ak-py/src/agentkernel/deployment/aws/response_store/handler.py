import os

from ...common.response_store import ResponseStore
from ....core.model import ResponseDB


class ResponseDBHandler:
    """
    Chooses the correct ResponseStore implementation based on environment variables.
    """

    def __init__(self):

        db_type = os.getenv("RESPONSE_DB")

        if db_type == ResponseDB.REDIS.value:
            from .redis import RedisResponseStore

            self.store = RedisResponseStore(
                host=os.getenv("REDIS_HOST"), # TODO:: Get these env vars from AkCOnfig and check terraform ones for ENV VAR Names
                port=int(os.getenv("REDIS_PORT", 6379)),
                username=os.getenv("REDIS_USERNAME"),
                password=os.getenv("REDIS_PASSWORD"),
                ssl=True
            )

        elif db_type == ResponseDB.DYNAMODB.value:
            from .dynamodb import DynamoDBResponseStore

            self.store = DynamoDBResponseStore(
                table_name=os.getenv("DYNAMODB_TABLE"),
                region=os.getenv("AWS_REGION")
            )

        else:
            raise ValueError(f"RESPONSE_DB must be one of: {', '.join([db.value for db in ResponseDB])}")

    def get_store(self) -> ResponseStore:
        """
        Return the selected response store.

        :return: ResponseStore implementation
        """
        return self.store
