import logging
from enum import StrEnum
from typing import Self

from .....core.config import AKConfig
from ....common.response_store import ResponseStore

_logger = logging.getLogger("ak.response_db_handler")


class ResponseDBHandler:
    """
    Chooses the correct ResponseStore implementation based on AKConfig settings.
    """

    class Type(StrEnum):
        """
        Enumeration of supported response store types.
        """

        REDIS = "REDIS"
        DYNAMODB = "DYNAMODB"

        @classmethod
        def from_str(cls, type_str: str) -> Self:
            """
            Create a ResponseDBHandler.Type enum member from a string representation.

            This class method attempts to convert a string to its corresponding
            ResponseDBHandler.Type enum value. If the conversion fails, it logs a
            warning and returns None.

            :param type_str: The string representation of the response store type.
                Case-insensitive input is supported.

            :returns: The corresponding ResponseDBHandler.Type enum member.
                Returns None if the input string doesn't match any valid enum member.
            """
            try:
                return cls[type_str.upper()]
            except KeyError:
                _logger.warning(f"Invalid response store type '{type_str}'")
                return None

    def __init__(self):
        config = AKConfig.get()

        # Check if execution config and response_store are configured
        if not config.execution or not config.execution.response_store:
            raise ValueError("Execution response_store configuration is required but not found in AKConfig")

        response_store_config = config.execution.response_store
        response_store_type: ResponseDBHandler.Type = ResponseDBHandler.Type.from_str(response_store_config.type)

        # Check for Redis configuration
        if response_store_type == ResponseDBHandler.Type.REDIS and response_store_config.redis is not None:
            from .redis import RedisResponseStore

            redis_config = response_store_config.redis

            self.store = RedisResponseStore(
                url=redis_config.url,
                prefix=redis_config.prefix,
                ttl=redis_config.ttl,
            )

        # Check for DynamoDB configuration
        elif response_store_type == ResponseDBHandler.Type.DYNAMODB and response_store_config.dynamodb is not None:
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
