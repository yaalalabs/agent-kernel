import logging
import json

import boto3

from ...common.chat_service import ChatService
from ....core.config import AKConfig
from .core.sqs_consumer import LambdaSQSConsumer

class ServerlessAgentRunner(LambdaSQSConsumer):
    
    _log = logging.getLogger("ak.aws.agentrunner")
    _chat_service = None
    _sqs_client = None

    @classmethod
    def _get_chat_service(cls) -> ChatService:
        if cls._chat_service is None:
            cls._chat_service = ChatService()
        return cls._chat_service

    @classmethod
    def _get_output_queue_url(cls) -> str:
        return AKConfig.get().execution.queues.output_queue_url

    @classmethod
    def _get_sqs_client(cls):
        if cls._sqs_client is None:
            cls._sqs_client = boto3.client("sqs")
        return cls._sqs_client

    @classmethod
    def _construct_queue_input_message(cls, raw_queue_message: dict, queue_input_message_body: dict) -> dict:
        """
        Construct the SQS message payload for the response queue.
        :param raw_queue_message: Original SQS message (``dict``) received by the Lambdafunction.
        :param queue_input_message_body: JSON-serializable body (``dict``) to be sent tothe response queue.
        :return: Dictionary (``dict``) of parameters for ``boto3`` ``send_message`` (excluding ``QueueUrl``).
        """
        return {
            "MessageGroupId": raw_queue_message["attributes"]["MessageGroupId"],
            "MessageDeduplicationId": raw_queue_message["attributes"]["MessageDeduplicationId"],
            "MessageBody": json.dumps(queue_input_message_body),
        }

    @classmethod
    def _construct_error_message_body(cls, error_msg: str) -> dict:
        """
        Build a standard error response body for failed message processing.
        :param error_msg: Human-readable error description (``str``).
        :return: Error payload (``dict``) to be sent to the response queue.
        """
        return {"error": error_msg}

    @classmethod
    def _send_to_output_queue(cls, queue_input_message: dict) -> None:
        """
        Send a prepared message to the configured response SQS queue.
        :param queue_input_message: Message payload (``dict``) as constructed by
        :return: None.
        """
        cls._get_sqs_client().send_message(
            QueueUrl=cls._get_output_queue_url(),
            **queue_input_message,
        )

    @classmethod
    def _parse_body(cls, record: dict) -> dict:
        """
        Parse the JSON body from an SQS record.
        :param record: SQS record (``dict``) passed from the Lambda event.
        :return: Parsed JSON body (``dict``) from the record.
        """
        return json.loads(record["body"])

    @classmethod
    def process_message(cls, record: dict) -> None:
        """
        Process a single SQS record, invoke the chat service, and send the response (or an error) to the output queue.
        :param record: SQS record (``dict``) containing the chat request payload.
        :return: None.
        """
        cls._log.info(f"Processing message: {record}")
        body = cls._parse_body(record)
        session_id = body.get("session_id")
        message_group_id = record.get("attributes").get("MessageGroupId")
        if session_id != message_group_id:
            cls._log.info(f"Session ID mismatch: message body session_id {session_id} does not match MessageGroupId {message_group_id}")
            error_message_body = cls._construct_error_message_body(error_msg="Session ID mismatch")
            queue_input_message = cls._construct_queue_input_message(raw_queue_message=record, queue_input_message_body=error_message_body,)
            cls._send_to_output_queue(queue_input_message=queue_input_message)
            cls._log.info(f"Sent Session ID Mismatch message to Output Queue: '{cls._get_output_queue_url()}'")
            return
        agent_response = cls._get_chat_service().process_chat_request(body=body)
        queue_input_message = cls._construct_queue_input_message(raw_queue_message=record, queue_input_message_body=agent_response,)
        cls._send_to_output_queue(queue_input_message=queue_input_message)
        cls._log.info(f"Sent Response message to Output Queue: '{cls._get_output_queue_url()}'")

    @classmethod
    def on_permanent_failure(cls, record: dict) -> None:
        """
        Handle messages that have reached their maximum retry count by sending an error response to the output queue.
        :param record: SQS record (``dict``) that failed processing after all retries.
        :return: None.
        """
        cls._log.info(f"Permanent failure: {record}: Retried message {cls.max_receive_count} times. Sending error message to Output Queue`")
        try:
            error_message_body = cls._construct_error_message_body(error_msg="Failed to process message. Retried {cls.max_receive_count} times")
            queue_input_message = cls._construct_queue_input_message(raw_queue_message=record, queue_input_message_body=error_message_body,)
            cls._send_to_output_queue(queue_input_message=queue_input_message)
            cls._log.info(f"Sent Permentant Failure message to Output Queue: '{cls._get_output_queue_url()}'")
        except Exception as e:
            # Message comes to this function only if the message has reached its maximum no of retries
            # Catching the error here so that this message will not be returned as batchItemFailures for another retry. 
            cls._log.info(f"Failed sending permenant failure message to Output Queue '{cls._get_output_queue_url()}' due to error: '{str(e)}'")