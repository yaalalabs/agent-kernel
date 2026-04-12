import logging
import json
from abc import ABC, abstractmethod
from typing import Any, Dict, List
from .....core import Runtime

class LambdaSQSConsumer(ABC):
    """
    Base class for AWS Lambda consumers triggered by an SQS Event Source Mapping.

    Subclasses should override `process_message` to implement business logic.
    """

    max_receive_count: int = 3  # Fallback value, actual configurable values are defined in the subclasses
    _log = logging.getLogger("ak.aws.lambdasqsconsumer")

    @classmethod
    def _parse_body(cls, record: dict) -> dict:
        """
        Parse the JSON body from an SQS record.
        :param record: SQS record (``dict``) passed from the Lambda event.
        :return: Parsed JSON body (``dict``) from the record.
        """
        return json.loads(record["body"])

    @classmethod
    def _is_message_processed(cls, session_id: str | None, message_id: str | None) -> bool:
        """
        Returns True if the message has already been processed for this session.
        """
        session = Runtime.current().sessions().load(session_id)
        nv_cache = session.get_non_volatile_cache()
        cls._log.info(f"Non-volatile cache for session {session_id}: {nv_cache}")
        last_message_id = nv_cache.get("last_message_id")
        if last_message_id == message_id:
            cls._log.info(f"Message {message_id} has already been processed for session {session_id}. Skipping.")
            return True
        return False

    @classmethod
    def _set_message_processed(cls, session_id: str | None, message_id: str | None) -> None:
        if not session_id or not message_id:
            return
        session = Runtime.current().sessions().load(session_id)
        session.get_non_volatile_cache().set("last_message_id", message_id)
        Runtime.current().sessions().store(session)

    @classmethod
    def handle(cls, event: Dict[str, Any], context: Any) -> Dict[str, Any]:
        """
        Main Lambda handler. Processes messages and builds a list of failures.
        :param event: Lambda event containing SQS Records
        :param context: Lambda context object
        :return: A dict with "batchItemFailures" per AWS format
        """
        failures: List[Dict[str, str]] = []
        records = event.get("Records", [])

        for record in records:
            message_id = record.get("messageId")
            attributes = record.get("attributes", {})
            # Get ApproximateReceiveCount (defaults to "1" if missing)
            receive_count = int(attributes.get("ApproximateReceiveCount", "1"))

            try:
                # Check if the message has been retired a lot
                if receive_count > cls.max_receive_count:
                    # Treated as permanently failed, skip business logic, this message could be sent to a DLQ or logged
                    cls.on_permanent_failure(record)
                    continue

                body = cls._parse_body(record)
                
                if cls._is_message_processed(session_id=body.get("session_id"), message_id=message_id):
                    continue
                
                # Normal processing path
                cls.process_message(record)

                cls._set_message_processed(session_id=body.get("session_id"), message_id=message_id)

            except Exception as exc:
                cls._log.info(f"Sending message as batchItemFailure '{message_id}': '{exc}'")
                # On failure, tell Lambda to return this message to the queue
                failures.append({"itemIdentifier": message_id})

        return {"batchItemFailures": failures}

    @classmethod
    @abstractmethod
    def process_message(cls, record: Dict[str, Any]) -> None:
        """
        Process a single SQS message.
        Subclasses must override this method.
        :param record: Single SQS record from event["Records"]
        :return: None
        """
        raise NotImplementedError("process_message must be implemented by subclasses")

    @classmethod
    @abstractmethod
    def on_permanent_failure(cls, record: Dict[str, Any]) -> None:
        """
        Called when a message is treated as permanently failed (retry limit reached).
        The default behavior does nothing, but subclasses can override
        to log, send to DLQ, send error message to user, metrics, etc.
        :param record: The SQS record that exceeded retry threshold
        :return: None
        """
        # To send the always failing message to a DLQ OR send error response to user OR
        pass
