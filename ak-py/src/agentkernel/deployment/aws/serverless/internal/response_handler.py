import logging
import json
from typing import Dict, Any

from agentkernel.deployment.aws.serverless.core.sqs_consumer import LambdaSQSConsumer
from agentkernel.deployment.aws.serverless.core.websocket_manager import WebSocketManager
from agentkernel.deployment.aws.response_store.handler import ResponseDBHandler
from agentkernel.core.config import AKConfig
from agentkernel.core.model import ExecutionMode


class RESTResponseHandler(LambdaSQSConsumer):
    """
    Lambda SQS consumer that processes response messages and stores them in the configured response store.
    """
    
    _log = logging.getLogger("ak.aws.responsehandler")
    _response_store = ResponseDBHandler().get_store()
    
    @classmethod
    def _construct_message_for_store(cls, record: Dict[str, Any], body: str = None) -> Dict[str, Any]:
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
        cls._response_store.add_message(message)

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
            cls._response_store.add_message(message)

            cls._log.info(f"Stored permanent failure message for session_id: {message['session_id']}, request_id: {message['request_id']}")
        except Exception as e:
            # Catch the error to prevent this message from being returned as batchItemFailures for another retry
            cls._log.error(f"Failed to store permanent failure message due to error: {str(e)}")


class WSResponseHandler(LambdaSQSConsumer):
    """
    Lambda SQS consumer that processes response messages and sends them via WebSocket connections.
    Used for async execution mode with WebSocket communication.
    """
    
    _log = logging.getLogger("ak.aws.wsresponsehandler")
    _ws_manager = WebSocketManager("ak.aws.wsresponsehandler")
    
    @classmethod
    def _parse_message_body(cls, record: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse the SQS message body to extract response data.
        
        :param record: SQS record
        :return: Parsed message data
        """
        try:
            body = record.get("body", "{}")
            if isinstance(body, str):
                message_data = json.loads(body)
            else:
                message_data = body
                
            return message_data
        except json.JSONDecodeError as e:
            cls._log.error(f"Failed to parse message body: {e}")
            raise
    
    @classmethod
    def process_message(cls, record: Dict[str, Any]) -> None:
        """
        Process a single SQS record and send it via WebSocket to the appropriate session.
        
        :param record: SQS record containing the response payload
        :return: None
        """
        cls._log.info(f"Processing WebSocket message: {record}")
        
        try:
            # Parse message body
            message_data = cls._parse_message_body(record)
            
            # Extract session_id from message attributes or body
            session_id = record.get("attributes", {}).get("MessageGroupId")
            if not session_id and "session_id" in message_data:
                session_id = message_data["session_id"]
            
            if not session_id:
                cls._log.error("No session_id found in message")
                raise ValueError("Missing session_id in message")
            
            # Extract WebSocket connection details
            domain_name, stage = cls._ws_manager.get_websocket_details_from_message(message_data)
            
            if not domain_name:
                cls._log.error("WebSocket domain_name not found in message or environment")
                raise ValueError("Missing WebSocket domain_name")
            
            # Prepare the response message for WebSocket
            ws_message = cls._ws_manager.create_websocket_message(
                message_type="response",
                session_id=session_id,
                request_id=message_data.get("request_id"),
                body=message_data,
                timestamp=message_data.get("timestamp")
            )
            
            # Send message to WebSocket connections
            success, successful_sends, total_connections = cls._ws_manager.send_message_to_all_session_connections(
                session_id, ws_message, domain_name, stage
            )
            
            if success:
                cls._log.info(f"Successfully sent WebSocket message for session_id: {session_id} "
                            f"({successful_sends}/{total_connections} connections)")
            else:
                cls._log.warning(f"Failed to send WebSocket message for session_id: {session_id}")
                
        except Exception as e:
            cls._log.error(f"Error processing WebSocket message: {e}")
            raise
    
    @classmethod
    def on_permanent_failure(cls, record: Dict[str, Any]) -> None:
        """
        Handle messages that have reached their maximum retry count.
        Sends an error message via WebSocket if possible.
        
        :param record: SQS record that failed processing after all retries
        :return: None
        """
        cls._log.error(f"Permanent WebSocket failure: {record}: Retried message {cls.max_receive_count} times")
        
        try:
            message_data = cls._parse_message_body(record)
            session_id = message_data.get("session_id")
            
            if not session_id:
                raise ValueError("Missing session_id in message for permanent failure handling")

            # Extract WebSocket connection details
            message_data = cls._parse_message_body(record)
            domain_name, stage = cls._ws_manager.get_websocket_details_from_message(message_data)
            
            if domain_name:
                # Create error message
                error_message = cls._ws_manager.create_websocket_message(
                    message_type="error",
                    session_id=session_id,
                    request_id=message_data.get("request_id"),
                    body=f"Failed to process message after {cls.max_receive_count} retries"
                )
                
                success, _, _ = cls._ws_manager.send_message_to_all_session_connections(
                    session_id, error_message, domain_name, stage
                )
                
                if success:
                    cls._log.info(f"Sent permanent failure message via WebSocket for session_id: {session_id}")
                else:
                    cls._log.error(f"Failed to send permanent failure message for session_id: {session_id}")
            else:
                cls._log.error("Cannot send WebSocket error message: missing domain_name")
            
        except Exception as e:
            # Catch the error to prevent this message from being returned as batchItemFailures for another retry
            cls._log.error(f"Failed to send permanent failure message via WebSocket: {str(e)}")


handler = WSResponseHandler.handle if AKConfig.get().execution.mode == ExecutionMode.ASYNC else RESTResponseHandler.handle