import asyncio
import time
from abc import ABC, abstractmethod
from typing import Dict

from ...core.config import AKConfig


class ResponseStore(ABC):
    """
    Abstract base class for response message storage systems.
    """

    _log = __import__("logging").getLogger("ak.deployment.response_store")

    @abstractmethod
    def add_message(self, message: Dict) -> None:
        """
        Store a response message.

        :param message: message containing request_id, session_id, body
        :return: None
        """
        pass

    @abstractmethod
    def get_message(self, request_id: str, get_and_delete: bool = False) -> Dict | None:
        """
        Retrieve a specific message by its request ID.

        :param request_id: Request ID
        :param get_and_delete: Delete the message after retrieval when True
        :return: message record as dict or None if not found
        """
        pass

    def get_message_with_retry(self, request_id: str, get_and_delete: bool = False, async_mode: bool = False):
        """
        Wait until a message exists for a request ID and retrieve it.

        :param request_id: Request ID
        :param get_and_delete: Delete the message after retrieval when True
        :param async_mode: If True, returns an awaitable that polls using
            asyncio.sleep/asyncio.to_thread instead of blocking, so an async caller
            can await it without holding a worker thread for the whole wait.
        :return: message record as dict or None if not found (or an awaitable of the same, when async_mode=True)
        """
        if async_mode:
            return self._get_message_with_retry_async(request_id, get_and_delete)

        retry_count, delay = self._get_retry_config()
        for attempt in range(retry_count):
            self._log.debug("Attempt %d/%d for request_id=%s", attempt + 1, retry_count, request_id)
            message = self.get_message(request_id, get_and_delete=get_and_delete)
            if message is not None:
                return message
            if attempt < retry_count - 1:
                time.sleep(delay)
        return None

    async def _get_message_with_retry_async(self, request_id: str, get_and_delete: bool = False) -> Dict | None:
        """
        Async counterpart of get_message_with_retry: yields the event loop via
        asyncio.sleep between attempts instead of blocking a thread for the full wait.
        """
        retry_count, delay = self._get_retry_config()
        for attempt in range(retry_count):
            self._log.debug("Attempt %d/%d for request_id=%s", attempt + 1, retry_count, request_id)
            message = await asyncio.to_thread(self.get_message, request_id, get_and_delete)
            if message is not None:
                return message
            if attempt < retry_count - 1:
                await asyncio.sleep(delay)
        return None

    @staticmethod
    def _get_retry_config() -> tuple[int, float]:
        """Read (retry_count, delay) for get_message_with_retry from config."""
        response_store_config = AKConfig.get().execution.response_store
        return response_store_config.retry_count, response_store_config.delay

    @abstractmethod
    def delete_message(self, request_id: str) -> None:
        """
        Delete a specific message.

        :param request_id: Request ID
        :return: None
        """
        pass
