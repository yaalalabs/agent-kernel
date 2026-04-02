import time
from abc import ABC, abstractmethod
from typing import Dict

from ...core.config import AKConfig


class ResponseStore(ABC):
    """
    Abstract base class for response message storage systems.
    """

    _log = __import__("logging").getLogger(__name__)

    @abstractmethod
    def add_message(self, message: Dict) -> None:
        """
        Store a response message.

        :param message: Message dictionary containing request_id, session_id, message_body
        :return: None
        """
        pass

    @abstractmethod
    def get_message(self, request_id: str, get_and_delete: bool = False) -> Dict | None:
        """
        Retrieve a specific message by its request ID.

        :param request_id: Request ID
        :param get_and_delete: Delete the message after retrieval when True
        :return: Message dictionary or None if not found
        """
        pass

    def get_message_with_retry(self, request_id: str, get_and_delete: bool = False) -> Dict | None:
        """
        Wait until a message exists for a request ID and retrieve it.
        :param request_id: Request ID
        :param get_and_delete: Delete the message after retrieval when True
        :return: Message dictionary or None if not found
        """
        response_store_config = AKConfig.get().execution.response_store
        retry_count = response_store_config.retry_count
        delay = response_store_config.delay
        for attempt in range(retry_count):
            self._log.debug("Attempt %d/%d for request_id=%s", attempt + 1, retry_count, request_id)
            message = self.get_message(request_id, get_and_delete=get_and_delete)
            if message is not None:
                return message
            if attempt < retry_count - 1:
                time.sleep(delay)
        return None

    @abstractmethod
    def delete_message(self, request_id: str) -> None:
        """
        Delete a specific message.

        :param request_id: Request ID
        :return: None
        """
        pass
