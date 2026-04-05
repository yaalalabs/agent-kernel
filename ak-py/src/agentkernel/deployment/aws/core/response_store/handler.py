from .....core.config import AKConfig
from ....common.response_store import ResponseStore


class ResponseDBHandler:
    """
    Chooses the correct ResponseStore implementation based on AKConfig settings.
    """

    def __init__(self):
        config = AKConfig.get()

        # Check if execution config and response_store are configured
        if not config.execution or not config.execution.response_store:
            raise ValueError("Execution response_store configuration is required but not found in AKConfig")

        response_store_config = config.execution.response_store

        # Check for Redis configuration
        if response_store_config.redis is not None:
            from .redis import RedisResponseStore

            redis_config = response_store_config.redis

            self.store = RedisResponseStore(
                url=redis_config.url,
                prefix=redis_config.prefix,
                ttl=redis_config.ttl,
            )

        # Check for DynamoDB configuration
        elif response_store_config.dynamodb is not None:
            from .dynamodb import DynamoDBResponseStore

            dynamodb_config = response_store_config.dynamodb

            self.store = DynamoDBResponseStore(
                table_name=dynamodb_config.table_name,
                region=None,  # Will use default AWS region from environment/IAM role
                ttl=dynamodb_config.ttl,
            )

        else:
            raise ValueError("No valid response store configured. Please configure either Redis or DynamoDB in execution.response_store")

    def get_store(self) -> ResponseStore:
        """
        Return the selected response store.

        :return: ResponseStore implementation
        """
        return self.store
