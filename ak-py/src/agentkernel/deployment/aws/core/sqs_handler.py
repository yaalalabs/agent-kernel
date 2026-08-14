from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

import boto3
from pydantic import BaseModel, ConfigDict

from ....core.config import AKConfig
from ....pipeline.transport import sqs as sqs_wire


class SQSHandler:
    """AWS deployment glue for building and sending SQS messages (serverless Lambda routing,
    WebSocket handlers, and external producers on the AWS queue mode). The public queue API is
    ``agentkernel.pipeline.transport`` (``QueueTransport``/``QueueMessage``); this class is the
    adapter-internal convenience surface on top of the same wire format.

    When used in a Non-Agent Kernel lambda/environment, the following environment variables
    must be exported:
    - AK_EXECUTION__QUEUES__INPUT__URL
    - AK_EXECUTION__QUEUES__OUTPUT__URL

    Since #495 the SQS wire-format primitives live in ``agentkernel.pipeline.transport.sqs``
    and are shared with the pipeline's SQSTransport (one implementation, so the two paths stay
    byte-identical on the wire). The aliased nested classes below keep this class's surface
    (user imports, isinstance checks, patch targets) intact.
    """

    _sqs_client = None
    _config = None
    _input_queue_url = None
    _output_queue_url = None

    AttributeDataType = sqs_wire.AttributeDataType
    SQSQueueInputMessage = sqs_wire.SQSQueueInputMessage
    CustomAttribute = sqs_wire.CustomAttribute

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
    def _get_config(cls):
        """Return a cached AKConfig instance.

        :return: A lazily created AKConfig instance.
        """
        if cls._config is None:
            cls._config = AKConfig.get()
        return cls._config

    @classmethod
    def get_input_queue_url(cls):
        """Return the cached input queue URL from config.

        :return: The input queue URL string.
        """
        if cls._input_queue_url is None:
            cls._input_queue_url = cls._get_config().execution.queues.input.url
        return cls._input_queue_url

    @classmethod
    def get_output_queue_url(cls):
        """Return the cached output queue URL from config.

        :return: The output queue URL string.
        """
        if cls._output_queue_url is None:
            cls._output_queue_url = cls._get_config().execution.queues.output.url
        return cls._output_queue_url

    @classmethod
    def get_sqs_client(cls):
        """Return a cached boto3 SQS client.

        :return: A lazily created boto3 SQS client instance.
        """
        if cls._sqs_client is None:
            cls._sqs_client = boto3.client("sqs")
        return cls._sqs_client

    @classmethod
    def _serialize_message_body(cls, message_body: Any) -> str:
        """Convert a message payload into the string body required by SQS
        (delegates to the shared pipeline wire helpers)."""
        return sqs_wire.serialize_message_body(message_body)

    @classmethod
    def _build_message_attribute(cls, custom_attribute: "SQSHandler.CustomAttribute") -> Dict[str, Any]:
        """Build a boto3-compatible SQS message attribute payload
        (delegates to the shared pipeline wire helpers)."""
        return sqs_wire.build_message_attribute(custom_attribute)

    @classmethod
    def _build_message_attributes(
        cls,
        message_attributes: list["SQSHandler.CustomAttribute"] | None,
    ) -> Optional[Dict[str, Any]]:
        """Convert a list of custom attributes into an SQS attributes map; rejects duplicate
        names (delegates to the shared pipeline wire helpers)."""
        return sqs_wire.build_message_attributes(message_attributes)

    @staticmethod
    def get_message_system_attributes(raw_queue_message_record: Mapping[str, Any]) -> Dict[str, Any]:
        """Return the SQS system attributes from a raw SQS message record, handling both Lambda
        event records and boto3 receive_message records (delegates to the shared pipeline wire
        helpers)."""
        return sqs_wire.get_message_system_attributes(raw_queue_message_record)

    @staticmethod
    def get_message_custom_attributes(raw_queue_message_record: Mapping[str, Any]) -> Dict[str, Any]:
        """Return the custom SQS message attributes from a raw SQS message record, handling both
        Lambda event records and boto3 receive_message records (delegates to the shared pipeline
        wire helpers)."""
        return sqs_wire.get_message_custom_attributes(raw_queue_message_record)

    @classmethod
    def build_send_message_kwargs(
        cls,
        message_body: Any,
        message_group_id: Optional[str] = None,
        message_deduplication_id: Optional[str] = None,
        message_attributes: list["SQSHandler.CustomAttribute"] | None = None,
        **extra_kwargs: Any,
    ) -> Dict[str, Any]:
        """
        Assemble the keyword arguments expected by boto3 send_message
        (delegates to the shared pipeline wire helpers).

        :param message_body: The payload to place in the SQS message body
        :param message_group_id: The FIFO message group id, if required
        :param message_deduplication_id: The FIFO deduplication id, if required
        :param message_attributes: Optional custom SQS message attributes
        :param extra_kwargs: Additional send_message keyword arguments to include
        :return: A dictionary of boto3 send_message keyword arguments
        """
        return sqs_wire.build_send_message_kwargs(
            message_body=message_body,
            message_group_id=message_group_id,
            message_deduplication_id=message_deduplication_id,
            message_attributes=message_attributes,
            **extra_kwargs,
        )

    @classmethod
    def send_message(
        cls,
        queue_url: str,
        message_body: Any,
        message_group_id: Optional[str] = None,
        message_deduplication_id: Optional[str] = None,
        message_attributes: list["SQSHandler.CustomAttribute"] | None = None,
        **extra_kwargs: Any,
    ):
        """
        Serialize a payload and send it to SQS.

        The method builds boto3-compatible keyword arguments, injects the target
        queue URL, and delegates the actual send to the cached SQS client.

        :param queue_url: The destination SQS queue URL
        :param message_body: The payload to send
        :param message_group_id: The FIFO message group id, if required
        :param message_deduplication_id: The FIFO deduplication id, if required
        :param message_attributes: Optional custom SQS message attributes
        :param extra_kwargs: Additional send_message keyword arguments to include
        :return: The boto3 send_message response
        """
        message_kwargs = cls.build_send_message_kwargs(
            message_body=message_body,
            message_group_id=message_group_id,
            message_deduplication_id=message_deduplication_id,
            message_attributes=message_attributes,
            **extra_kwargs,
        )
        return cls.get_sqs_client().send_message(QueueUrl=queue_url, **message_kwargs)

    @classmethod
    def send_prepared_message(cls, queue_url: str, message_kwargs: Mapping[str, Any]):
        """
        Send a pre-built message payload to SQS.

        Use this when the caller has already prepared a boto3-compatible message
        payload and only needs the queue URL injected at send time.

        :param queue_url: The destination SQS queue URL
        :param message_kwargs: A mapping of boto3 send_message keyword arguments
        :return: The boto3 send_message response
        """
        return cls.get_sqs_client().send_message(QueueUrl=queue_url, **dict(message_kwargs))

    @classmethod
    def _build_standard_message_attributes(
        cls,
        request_id: Optional[str],
        user_id: Optional[str],
        custom_message_attributes: Optional[List["SQSHandler.CustomAttribute"]],
    ) -> Optional[List["SQSHandler.CustomAttribute"]]:
        """
        Combine the standard request_id/user_id attributes with caller-supplied ones.

        :param request_id: Optional request ID custom attribute
        :param user_id: Optional user ID custom attribute
        :param custom_message_attributes: Additional custom message attributes
        :return: The combined attribute list, or None when there are no attributes
        """
        message_attributes = []
        if request_id is not None:
            message_attributes.append(cls.CustomAttribute(name="request_id", value=request_id, datatype=cls.AttributeDataType.STRING))
        if user_id is not None:
            message_attributes.append(cls.CustomAttribute(name="user_id", value=user_id, datatype=cls.AttributeDataType.STRING))

        message_attributes.extend(custom_message_attributes or [])
        return message_attributes if message_attributes else None

    @staticmethod
    def _get_session_id(message_body: Any) -> Optional[str]:
        """
        Extract session_id from a message body, if present.

        :param message_body: A mapping, Pydantic model, or arbitrary payload
        :return: The session_id value, or None when the body does not carry one
        """
        if isinstance(message_body, Mapping):
            return message_body.get("session_id")
        return getattr(message_body, "session_id", None)

    @classmethod
    def send_message_to_input_queue(
        cls,
        message_body: "SQSHandler.QueueMessageBody | Dict[str, Any]",
        attributes: "SQSHandler.SendMessageAttributes | Dict[str, Any] | None" = None,
        request_id: Optional[str] = None,
        user_id: Optional[str] = None,
        custom_message_attributes: Optional[List["SQSHandler.CustomAttribute"]] = None,
        **extra_kwargs: Any,
    ):
        """
        Send a message to the input queue with standard custom attributes.

        This method handles the common pattern of sending messages to the input queue
        with request_id and user_id as custom message attributes. The FIFO message
        group id defaults to the body's session_id unless overridden via attributes.

        :param message_body: The payload to send; must contain prompt and session_id, and may contain agent (extra fields are preserved)
        :param attributes: Optional FIFO send attributes (message_group_id, message_deduplication_id)
        :param request_id: Optional request ID custom attribute
        :param user_id: Optional user ID custom attribute
        :param custom_message_attributes: Additional custom message attributes
        :param extra_kwargs: Additional send_message keyword arguments to include
        :return: The boto3 send_message response
        :raises ValueError: If input queue URL is not configured
        :raises pydantic.ValidationError: If message_body is missing prompt or session_id
        """
        queue_url = cls.get_input_queue_url()
        if not queue_url:
            raise ValueError("Input queue URL is not configured in AKConfig")

        body = cls.QueueMessageBody.model_validate(message_body)
        send_attributes = cls.SendMessageAttributes.model_validate(attributes or {})

        return cls.send_message(
            queue_url=queue_url,
            message_body=body,
            message_group_id=send_attributes.message_group_id or body.session_id,
            message_deduplication_id=send_attributes.message_deduplication_id,
            message_attributes=cls._build_standard_message_attributes(request_id, user_id, custom_message_attributes),
            **extra_kwargs,
        )

    @classmethod
    def send_message_to_output_queue(
        cls,
        message_body: Any,
        attributes: "SQSHandler.SendMessageAttributes | Dict[str, Any] | None" = None,
        request_id: Optional[str] = None,
        user_id: Optional[str] = None,
        custom_message_attributes: Optional[List["SQSHandler.CustomAttribute"]] = None,
        **extra_kwargs: Any,
    ):
        """
        Send a message to the output queue with standard custom attributes.

        This method handles the common pattern of sending messages to the output queue
        with request_id and user_id as custom message attributes. The FIFO message
        group id defaults to the body's session_id (when the body carries one) unless
        overridden via attributes.

        :param message_body: The payload to send
        :param attributes: Optional FIFO send attributes (message_group_id, message_deduplication_id)
        :param request_id: Optional request ID custom attribute
        :param user_id: Optional user ID custom attribute
        :param custom_message_attributes: Additional custom message attributes
        :param extra_kwargs: Additional send_message keyword arguments to include
        :return: The boto3 send_message response
        :raises ValueError: If output queue URL is not configured
        """
        queue_url = cls.get_output_queue_url()
        if not queue_url:
            raise ValueError("Output queue URL is not configured in AKConfig")

        send_attributes = cls.SendMessageAttributes.model_validate(attributes or {})

        return cls.send_message(
            queue_url=queue_url,
            message_body=message_body,
            message_group_id=send_attributes.message_group_id or cls._get_session_id(message_body),
            message_deduplication_id=send_attributes.message_deduplication_id,
            message_attributes=cls._build_standard_message_attributes(request_id, user_id, custom_message_attributes),
            **extra_kwargs,
        )
