from __future__ import annotations

import json
import logging

from ....core.chat_service import ChatService
from ....core.config import AKConfig
from ....core.model import BaseRunRequest
from ..core.sqs_handler import SQSHandler
from .sqs_poller import SQSPoller


class ECSAgentRunner:
    """
    ECS Agent Runner — polls the Input Queue, runs the agent, and puts
    the result on the Output Queue.

    This is the ECS equivalent of ``ServerlessAgentRunner``.  Instead of
    being triggered by a Lambda Event Source Mapping, it runs a blocking
    ``SQSPoller`` loop (meant to be the container's main process).

    Usage::

        if __name__ == "__main__":
            ECSAgentRunner.run()
    """

    _log = logging.getLogger("ak.ecs.agentrunner")
    _chat_service: ChatService | None = None
    _config = AKConfig.get()

    # ------------------------------------------------------------------
    # Public entrypoint
    # ------------------------------------------------------------------

    @classmethod
    def run(cls) -> None:
        """
        Start the blocking poll loop.  Call this as the container entry-point.
        """
        config = cls._config
        input_queue_url = config.execution.queues.input.url
        max_receive_count = config.execution.queues.input.max_receive_count

        if not input_queue_url:
            raise ValueError(
                "AK_EXECUTION__QUEUES__INPUT__URL is required for ECSAgentRunner"
            )

        cls._log.info(f"ECSAgentRunner starting — input queue: {input_queue_url}")

        poller = SQSPoller(
            queue_url=input_queue_url,
            process_fn=cls.process_message,
            max_receive_count=max_receive_count,
            on_permanent_failure_fn=cls.on_permanent_failure,
        )
        poller.run()  # blocks forever

    # ------------------------------------------------------------------
    # Message processing (same logic as ServerlessAgentRunner)
    # ------------------------------------------------------------------

    @classmethod
    def _get_chat_service(cls) -> ChatService:
        if cls._chat_service is None:
            cls._chat_service = ChatService()
        return cls._chat_service

    @classmethod
    def _get_record_attributes(cls, raw_queue_message: dict) -> dict:
        """
        Extract routing attributes from a raw SQS message.

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
        """
        Process a single SQS message: run the agent and put the response
        on the Output Queue.

        :param record: boto3 SQS message dict
        """
        cls._log.info(f"Processing message {record.get('MessageId')}")
        body = BaseRunRequest.model_validate(json.loads(record["Body"]))
        _, agent_response = cls._get_chat_service().process_chat_request(req=body)
        record_attributes = cls._get_record_attributes(raw_queue_message=record)
        cls._send_to_output_queue(message_body=agent_response, record_attributes=record_attributes)
        cls._log.info(
            f"Sent response to output queue: {SQSHandler.get_output_queue_url()}"
        )

    @classmethod
    def on_permanent_failure(cls, record: dict) -> None:
        """
        Handle a message that exceeded max retries — send an error response
        to the Output Queue so the REST Service can return it to the caller.

        :param record: boto3 SQS message dict
        """
        cls._log.error(
            f"Permanent failure for message {record.get('MessageId')}"
        )
        try:
            record_attributes = cls._get_record_attributes(raw_queue_message=record)
            error_body = {
                "error": f"Failed to process message after "
                         f"{cls._config.execution.queues.input.max_receive_count} retries"
            }
            cls._send_to_output_queue(
                message_body=error_body, record_attributes=record_attributes
            )
        except Exception:
            cls._log.exception(
                "Failed to send permanent-failure error to output queue"
            )
