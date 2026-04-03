import logging
import json
from typing import Dict, Any, Optional

from .core.sqs_consumer import LambdaSQSConsumer
from ..response_store import ResponseDBHandler


class ResponseHandler(LambdaSQSConsumer):
    """
    Lambda SQS consumer that processes response messages and stores them in the configured response store.
    """
    
    _log = logging.getLogger("ak.aws.responsehandler")
    _response_store = None

    @classmethod
    def _get_response_store(cls):
        if cls._response_store is None:
            cls._response_store = ResponseDBHandler().get_store()
        return cls._response_store
    
    @classmethod
    def _construct_message_for_store(cls, record: Dict[str, Any], body: Optional[str] = None) -> Dict[str, Any]:
        """
        Construct the message object to be stored in the response store.

        :param record: SQS record
        :param body: Optional message body string. If not provided, uses record["body"]
        :return: Message dictionary for storage
        """
        session_id = record.get("attributes", {}).get("MessageGroupId")
        message_body = body if body is not None else record.get("body")
        message_body = json.loads(message_body)
        request_id = message_body.get("request_id")
        message = {
            "session_id": session_id,
            "request_id": request_id,
            "body": message_body
        }
        return message
    
    @classmethod
    def process_message(cls, record: Dict[str, Any]) -> None:
        """
        Process a single SQS record and store it in the response store.

        :param record: SQS record containing the response payload
        :return: None
        """
        cls._log.info(f"Processing message: {record}")

        message = cls._construct_message_for_store(record)
        cls._get_response_store().add_message(message)

        cls._log.info(f"Stored message for session_id: {message['session_id']}, request_id: {message['request_id']}")
    
    @classmethod
    def on_permanent_failure(cls, record: Dict[str, Any]) -> None:
        """
        Handle messages that have reached their maximum retry count.
        Logs the failure and optionally stores an error message in the response store.

        :param record: SQS record that failed processing after all retries
        :return: None
        """
        cls._log.error(f"Permanent failure: {record}: Retried message {cls.max_receive_count} times")

        try:
            # Store an error message in the response store
            original_body = record.get("body")
            if isinstance(original_body, str):
                try:
                    original_body = json.loads(original_body)
                except json.JSONDecodeError:
                    original_body = {}

            request_id = original_body.get("request_id") if isinstance(original_body, dict) else None
            error_body = json.dumps({
                "error": f"Failed to process message after {cls.max_receive_count} retries",
                "request_id": request_id,
            })

            message = cls._construct_message_for_store(record, body=error_body)
            cls._get_response_store().add_message(message)

            cls._log.info(f"Stored permanent failure message for session_id: {message['session_id']}, request_id: {message['request_id']}")
        except Exception as e:
            # Catch the error to prevent this message from being returned as batchItemFailures for another retry
            cls._log.error(f"Failed to store permanent failure message due to error: {str(e)}")