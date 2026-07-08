from abc import ABC, abstractmethod
from typing import Any, List, Optional


class QueueHandler(ABC):
    """
    Abstract base class for input/output queue messaging handlers.
    """

    @classmethod
    @abstractmethod
    def send_message_to_input_queue(
        cls,
        message_group_id: Optional[str] = None,
        message_deduplication_id: Optional[str] = None,
        message_body: Optional[Any] = None,
        request_id: Optional[str] = None,
        user_id: Optional[str] = None,
        custom_message_attributes: Optional[List[Any]] = None,
        **extra_kwargs: Any,
    ) -> Any:
        """
        Send a message to the input queue.

        :param message_group_id: The FIFO message group id, if required
        :param message_deduplication_id: The FIFO deduplication id, if required
        :param message_body: The payload to send
        :param request_id: Optional request ID custom attribute
        :param user_id: Optional user ID custom attribute
        :param custom_message_attributes: Additional custom message attributes
        :param extra_kwargs: Additional implementation-specific keyword arguments
        :return: The underlying queue provider's send response
        """
        pass

    @classmethod
    @abstractmethod
    def send_message_to_output_queue(
        cls,
        message_group_id: Optional[str] = None,
        message_deduplication_id: Optional[str] = None,
        message_body: Optional[Any] = None,
        request_id: Optional[str] = None,
        user_id: Optional[str] = None,
        custom_message_attributes: Optional[List[Any]] = None,
        **extra_kwargs: Any,
    ) -> Any:
        """
        Send a message to the output queue.

        :param message_group_id: The FIFO message group id, if required
        :param message_deduplication_id: The FIFO deduplication id, if required
        :param message_body: The payload to send
        :param request_id: Optional request ID custom attribute
        :param user_id: Optional user ID custom attribute
        :param custom_message_attributes: Additional custom message attributes
        :param extra_kwargs: Additional implementation-specific keyword arguments
        :return: The underlying queue provider's send response
        """
        pass
