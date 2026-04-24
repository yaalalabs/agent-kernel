import json
import logging

from ....core.config import AKConfig
from ....core.chat_service import ChatService
from ....core.model import BaseRunRequest
from ..core.sqs_handler import SQSHandler
from .core import LambdaSQSConsumer


class ServerlessAgentRunner(LambdaSQSConsumer):

    _log = logging.getLogger("ak.aws.agentrunner")
    _chat_service = None
    max_receive_count: int = AKConfig.get().execution.queues.input.max_receive_count

    @classmethod
    def _get_chat_service(cls) -> ChatService:
        if cls._chat_service is None:
            cls._chat_service = ChatService()
        return cls._chat_service

    @classmethod
    def _get_record_attributes(cls, raw_queue_message: dict) -> dict:
        """
        Extract attributes from the raw SQS message record.
        :param raw_queue_message: Original SQS message (``dict``) received by the Lambda function.
        :return: Dictionary (``dict``) containing extracted attributes.
        """
        attributes = SQSHandler.get_message_system_attributes(raw_queue_message)
        message_attributes = SQSHandler.get_message_custom_attributes(raw_queue_message)
        request_id = message_attributes.get("request_id")
        user_id = message_attributes.get("user_id")

        if not request_id:
            raise ValueError("request_id is required")

        record_attributes = {
            "message_group_id": attributes["MessageGroupId"],
            "message_deduplication_id": attributes.get("MessageDeduplicationId"),
            "request_id": request_id,
            "user_id": user_id,
        }

        cls._log.info(f"Extracted record attributes: {record_attributes}")
        return record_attributes

    @classmethod
    def _construct_error_message_body(cls, error_msg: str) -> dict:
        """
        Build a standard error response body for failed message processing.
        :param error_msg: Human-readable error description (``str``).
        :return: Error payload (``dict``) to be sent to the response queue.
        """
        return {"error": error_msg}

    @classmethod
    def _send_to_output_queue(cls, message_body: dict, record_attributes: dict) -> None:
        """
        Send a prepared message to the configured response SQS queue using send_message_to_output_queue.
        :param message_body: Message body (``dict``) to be sent to the response queue.
        :param record_attributes: Extracted attributes (``dict``) from the record.
        :return: None.
        """
        SQSHandler.send_message_to_output_queue(
            message_group_id=record_attributes["message_group_id"],
            message_deduplication_id=record_attributes["message_deduplication_id"],
            message_body=message_body,
            request_id=record_attributes["request_id"],
            user_id=record_attributes["user_id"],
        )

    @classmethod
    def _parse_body(cls, record: dict) -> BaseRunRequest:
        """
        Parse the JSON body from an SQS record.
        :param record: SQS record (``dict``) passed from the Lambda event.
        :return: Parsed JSON body as ``BaseRunRequest`` from the record.
        """
        return BaseRunRequest.model_validate(json.loads(record["body"]))

    @classmethod
    def process_message(cls, record: dict) -> None:
        """
        Process a single SQS record, invoke the chat service, and send the response (or an error) to the output queue.
        :param record: SQS record (``dict``) containing the chat request payload.
        :return: None.
        """
        cls._log.info(f"Processing message: {record}")
        body = cls._parse_body(record)
        _, agent_response = cls._get_chat_service().process_chat_request(req=body)
        cls._log.info(f"Chat service response: '{agent_response}'")
        record_attributes = cls._get_record_attributes(raw_queue_message=record)
        cls._send_to_output_queue(message_body=agent_response, record_attributes=record_attributes)
        cls._log.info(f"Sent Response message to Output Queue: '{SQSHandler.get_output_queue_url()}'")

    @classmethod
    def on_permanent_failure(cls, record: dict) -> None:
        """
        Handle messages that have reached their maximum retry count by sending an error response to the output queue.
        :param record: SQS record (``dict``) that failed processing after all retries.
        :return: None.
        """
        cls._log.info(f"Permanent failure: {record}: Retried message {cls.max_receive_count} times. Sending error message to Output Queue`")
        try:
            error_message_body = cls._construct_error_message_body(error_msg=f"Failed to process message. Retried {cls.max_receive_count} times")
            record_attributes = cls._get_record_attributes(raw_queue_message=record)
            cls._send_to_output_queue(message_body=error_message_body, record_attributes=record_attributes)
            cls._log.info(f"Sent Permanent Failure message to Output Queue: '{SQSHandler.get_output_queue_url()}'")
        except Exception as e:
            # Message comes to this function only if the message has reached its maximum no of retries
            # Catching the error here so that this message will not be returned as batchItemFailures for another retry.
            cls._log.info(f"Failed sending permanent failure message to Output Queue '{SQSHandler.get_output_queue_url()}' due to error: '{str(e)}'")
