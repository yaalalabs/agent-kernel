from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict


class ChatQueueHandler(ABC):
    """
    Abstract base class for the chat-shaped queue send surface: sending chat request/reply
    bodies (prompt/session_id/agent) to the input and output queues.

    This is the deployment adapters' send-side contract (implemented by SQSHandler, used by the
    ECS/Lambda queue mode and external producers). The pipeline's generic send abstraction is
    ``agentkernel.pipeline.transport.QueueTransport``, which speaks ``QueueMessage`` envelopes;
    the pipeline adapts to this class's call signature without implementing it.
    """

    class SendMessageAttributes(BaseModel):
        """FIFO send attributes for the input/output queue convenience methods.

        Unknown keys are rejected so that attribute typos fail fast instead of
        silently sending the message without the intended FIFO ids.
        """

        message_group_id: Optional[str] = None
        message_deduplication_id: Optional[str] = None

        model_config = ConfigDict(extra="forbid")

    class QueueMessageBody(BaseModel):
        """Typed message body for the input queue. Extra fields are allowed and preserved.

        agent is optional; when omitted, the runtime selects the first registered agent.
        """

        prompt: str
        agent: Optional[str] = None
        session_id: str

        model_config = ConfigDict(extra="allow")

    @classmethod
    @abstractmethod
    def send_message_to_input_queue(
        cls,
        message_body: "ChatQueueHandler.QueueMessageBody | Dict[str, Any]",
        attributes: "ChatQueueHandler.SendMessageAttributes | Dict[str, Any] | None" = None,
        request_id: Optional[str] = None,
        user_id: Optional[str] = None,
        custom_message_attributes: Optional[List[Any]] = None,
        **extra_kwargs: Any,
    ) -> Any:
        """
        Send a message to the input queue.

        :param message_body: The payload to send; must contain prompt and session_id, and may contain agent (extra fields are preserved)
        :param attributes: Optional FIFO send attributes (message_group_id, message_deduplication_id);
            message_group_id defaults to the body's session_id when not provided
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
        message_body: Any,
        attributes: "ChatQueueHandler.SendMessageAttributes | Dict[str, Any] | None" = None,
        request_id: Optional[str] = None,
        user_id: Optional[str] = None,
        custom_message_attributes: Optional[List[Any]] = None,
        **extra_kwargs: Any,
    ) -> Any:
        """
        Send a message to the output queue.

        :param message_body: The payload to send
        :param attributes: Optional FIFO send attributes (message_group_id, message_deduplication_id);
            message_group_id defaults to the body's session_id when the body carries one
        :param request_id: Optional request ID custom attribute
        :param user_id: Optional user ID custom attribute
        :param custom_message_attributes: Additional custom message attributes
        :param extra_kwargs: Additional implementation-specific keyword arguments
        :return: The underlying queue provider's send response
        """
        pass


# Backwards-compatible alias: the pre-rename public name. Existing imports and subclasses
# (`class MyHandler(QueueHandler)`) keep working; new code uses ChatQueueHandler.
QueueHandler = ChatQueueHandler
