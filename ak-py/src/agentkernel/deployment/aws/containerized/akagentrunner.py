from __future__ import annotations

import json
import logging

from ....core.chat_service import ChatService
from ....core.config import AKConfig
from ....core.model import BaseRunRequest
from ..core.sqs_handler import SQSHandler
from .core import ECSSQSConsumer


class ECSAgentRunner(ECSSQSConsumer):
    """
    ECS Agent Runner — polls the Input Queue, runs the agent, and puts
    the result on the Output Queue.

    The ECS equivalent of ServerlessAgentRunner. Instead of being triggered
    by a Lambda Event Source Mapping, it inherits run() from ECSSQSConsumer,
    which drives a blocking long-poll loop — meant to be the container's
    main process.

    Usage::

        if __name__ == "__main__":
            ECSAgentRunner.run()
    """

    _log = logging.getLogger("ak.ecs.agentrunner")
    _chat_service: ChatService | None = None
    _config = AKConfig.get()
    max_receive_count = _config.execution.queues.input.max_receive_count

    @classmethod
    def _get_queue_url(cls) -> str:
        return cls._config.execution.queues.input.url

    @classmethod
    def _get_chat_service(cls) -> ChatService:
        if cls._chat_service is None:
            cls._chat_service = ChatService()
        return cls._chat_service

    @classmethod
    def _get_record_attributes(cls, raw_queue_message: dict) -> dict:
        """
        Extract routing attributes from a raw SQS message.

        Works with both boto3 receive_message records (PascalCase keys)
        and Lambda event records (camelCase keys).

        :param raw_queue_message: boto3 SQS message dict
        :return: Extracted attributes dict
        :raises ValueError: If request_id is missing
        """
        attributes = SQSHandler.get_message_system_attributes(raw_queue_message)
        message_attributes = SQSHandler.get_message_custom_attributes(raw_queue_message)

        request_id = message_attributes.get("request_id")
        if not request_id:
            raise ValueError("request_id is required in SQS message attributes")

        return {
            # boto3: "MessageGroupId" under Attributes; Lambda: "MessageGroupId" under attributes
            "message_group_id": attributes.get("MessageGroupId"),
            "message_deduplication_id": attributes.get("MessageDeduplicationId"),
            "request_id": request_id,
            "user_id": message_attributes.get("user_id"),
        }

    @classmethod
    def _send_to_output_queue(cls, message_body: dict, record_attributes: dict) -> None:
        SQSHandler.send_message_to_output_queue(
            message_group_id=record_attributes["message_group_id"],
            message_deduplication_id=record_attributes["message_deduplication_id"],
            message_body=message_body,
            request_id=record_attributes["request_id"],
            user_id=record_attributes["user_id"],
        )

    @classmethod
    def process_message(cls, record: dict) -> None:
        """Implements ECSSQSConsumer.process_message."""
        message_id = record.get("MessageId")
        cls._log.info(f"[AGENT START] Processing message {message_id}")

        body = BaseRunRequest.model_validate(json.loads(record["Body"]))
        record_attributes = cls._get_record_attributes(raw_queue_message=record)

        cls._log.info(
            f"[AGENT PROCESSING] request_id={record_attributes['request_id']}, "
            f"session_id={body.session_id}, agent={body.agent}, prompt={body.prompt[:50] if body.prompt else 'N/A'}"
        )

        _, agent_response = cls._get_chat_service().process_chat_request(req=body)

        cls._log.info(
            f"[AGENT RESPONSE] request_id={record_attributes['request_id']}, "
            f"response_keys={list(agent_response.keys()) if isinstance(agent_response, dict) else 'N/A'}"
        )

        cls._send_to_output_queue(message_body=agent_response, record_attributes=record_attributes)

        cls._log.info(f"[AGENT DONE] Sent to output queue: {SQSHandler.get_output_queue_url()}, " f"request_id={record_attributes['request_id']}")

    @classmethod
    def on_permanent_failure(cls, record: dict) -> None:
        """Implements ECSSQSConsumer.on_permanent_failure. Catches own exceptions."""
        cls._log.error(f"Permanent failure for message {record.get('MessageId')}")
        try:
            record_attributes = cls._get_record_attributes(raw_queue_message=record)
            error_body = {"error": f"Failed to process message after " f"{cls._config.execution.queues.input.max_receive_count} retries"}
            cls._send_to_output_queue(message_body=error_body, record_attributes=record_attributes)
        except Exception:
            cls._log.exception("Failed to send permanent-failure error to output queue")
