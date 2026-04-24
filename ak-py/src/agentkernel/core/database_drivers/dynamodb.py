import json
import logging
import time
from typing import Optional
import boto3



class BaseDynamoDBDriver:
    """
    BaseDynamoDBDriver provides common connection management and helpers for
    DynamoDB operations, to be extended by specific drivers like session or
    attachment drivers.
    """

    _log = logging.getLogger("ak.core.database_drivers.dynamodb.base_driver")

    def __init__(self, table_name: str, logger_name = None):
      
        self._table_name = table_name
        self._table = None
        self.log = logging.getLogger(logger_name or self.__class__.__name__)

    @property
    def table(self):
        """
        Returns the boto3 DynamoDB Table resource, connecting lazily if needed.
        :return: The DynamoDB Table resource.
        """
        if self._table is None:
            self._connect()
        return self._table

    def _connect(self):
        """
        Establish a connection to DynamoDB and resolve the configured table.

        Retries a few times with a small delay between attempts. Raises the last
        encountered exception if all attempts fail.
        """
        

        retries = 3
        delay = 2
        last_err: Optional[Exception] = None
        for attempt in range(retries):
            try:
                self._log.debug("Connecting to DynamoDB resource")
                resource = boto3.resource("dynamodb")
                self._table = resource.Table(self._table_name)
                self._table.load()
                self._log.debug("Connected to DynamoDB table %s", self._table_name)
                return
            except Exception as e:
                last_err = e
                self._log.warning(
                    "Attempt %d: Failed to connect to DynamoDB table %s: %s",
                    attempt + 1,
                    self._table_name,
                    e,
                )
                if attempt < retries - 1:
                    time.sleep(delay)
        if last_err:
            raise last_err