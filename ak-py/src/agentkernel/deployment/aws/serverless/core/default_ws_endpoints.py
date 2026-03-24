from __future__ import annotations

import json
import logging
import traceback
import uuid
from typing import Any, Callable, Dict

import boto3

from .....core.config import AKConfig
from .websocket_manager import WebSocketManager


class DefaultWebsocketRouteHandler:
    """Provides default WebSocket endpoint routes for real-time communication."""

    _log = logging.getLogger("ak.aws.lambda.default_ws_endpoints")
    _ws_manager = WebSocketManager("ak.aws.lambda.default_ws_endpoints")

    _config = AKConfig.get()
    _input_queue_url = _config.execution.input_queue_url

    # WebSocket route constants
    _connect_route = "$connect"
    _disconnect_route = "$disconnect"
    _default_route = "$default"
    _chat_route = "chat"

    # AWS clients
    _sqs = boto3.client("sqs")
        
    @classmethod
    def get_routes(cls) -> Dict[str, Callable]:
        """
        Return WebSocket route mappings.
        :return: Dictionary mapping route names to handler functions
        """
        cls._log.info("Initialized WebSocket endpoints.")
        
        routes = {
            cls._connect_route: cls._handle_ws_connection,
            cls._disconnect_route: cls._handle_ws_disconnection,
            cls._default_route: cls._handle_default_message,
            cls._chat_route: cls._handle_chat_message,
        }
            
        return routes

    @classmethod
    def _handle_ws_connection(cls, event: Dict[str, Any], context: Any) -> Dict[str, Any]:
        """
        Handle WebSocket connection establishment.
        :param event: API Gateway WebSocket event
        :param context: Lambda context
        :return: Connection response
        """
        try:
            connection_id = event["requestContext"]["connectionId"]
            query_params = event.get("queryStringParameters") or {}
            session_id = query_params.get("session_id")

            if not session_id:
                cls._log.warning(f"Connection {connection_id} missing session_id")
                return {"statusCode": 400, "body": "Missing session_id parameter"}

            # Store connection using WebSocket manager
            success = cls._ws_manager.store_connection(
                session_id=session_id,
                connection_id=connection_id,
                metadata={
                    "connected_at": int(context.get_remaining_time_in_millis() if context else 0)
                }
            )

            if success:
                cls._log.info(f"WebSocket connected: {connection_id} for session: {session_id}")
                return {"statusCode": 200}
            else:
                cls._log.error(f"Failed to store connection {connection_id}")
                return {"statusCode": 500, "body": "Failed to store connection"}

        except Exception as e:
            cls._log.error(f"Connection error: {e}\n{traceback.format_exc()}")
            return {"statusCode": 500, "body": f"Connection failed: {str(e)}"}
    @classmethod
    def _handle_ws_disconnection(cls, event: Dict[str, Any], context: Any) -> Dict[str, Any]:
        """
        Handle WebSocket disconnection.
        :param event: API Gateway WebSocket event
        :param context: Lambda context
        :return: Disconnection response
        """
        try:
            connection_id = event["requestContext"]["connectionId"]
            
            # Remove connection using WebSocket manager
            success = cls._ws_manager.remove_connection_by_id(connection_id)
            
            if success:
                cls._log.info(f"WebSocket disconnected: {connection_id}")
            else:
                cls._log.warning(f"Connection {connection_id} not found or failed to remove")
            
            return {"statusCode": 200}

        except Exception as e:
            cls._log.error(f"Disconnection error: {e}\n{traceback.format_exc()}")
            return {"statusCode": 500, "body": f"Disconnection failed: {str(e)}"}
    @classmethod
    def _handle_default_message(cls, event: Dict[str, Any], context: Any) -> Dict[str, Any]:
        """
        Handle default/unknown WebSocket messages.
        :param event: API Gateway WebSocket event
        :param context: Lambda context
        :return: Default response
        """
        try:
            connection_id = event["requestContext"]["connectionId"]
            body = json.loads(event.get("body", "{}"))
            
            cls._log.warning(f"Received unknown message from {connection_id}: {body}")
            
            # Send error response back to client using WebSocket manager
            request_context = event.get("requestContext", {})
            domain_name = request_context.get("domainName")
            stage = request_context.get("stage")
            
            if domain_name and stage:
                cls._ws_manager.send_error_to_connection(
                    connection_id=connection_id,
                    error_message="Unknown message type. Use 'chat' route for chat messages.",
                    domain_name=domain_name,
                    stage=stage
                )
            
            return {"statusCode": 200}

        except Exception as e:
            cls._log.error(f"Default message error: {e}\n{traceback.format_exc()}")
            return {"statusCode": 500}

    @classmethod
    def _handle_chat_message(cls, event: Dict[str, Any], context: Any) -> Dict[str, Any]:
        """
        Handle chat message by adding it to the input queue.
        :param event: API Gateway WebSocket event
        :param context: Lambda context
        :return: Queue response
        """
        try:
            connection_id = event["requestContext"]["connectionId"]
            body = json.loads(event.get("body", "{}"))
            
            # Get session_id from connection using WebSocket manager
            session_id = cls._ws_manager.get_session_id_from_connection(connection_id)
            if not session_id:
                request_context = event.get("requestContext", {})
                domain_name = request_context.get("domainName")
                stage = request_context.get("stage")
                
                if domain_name and stage:
                    cls._ws_manager.send_error_to_connection(
                        connection_id=connection_id,
                        error_message="Session not found for connection",
                        domain_name=domain_name,
                        stage=stage
                    )
                return {"statusCode": 400}

            # Check if queue is configured
            if not cls._input_queue_url:
                request_context = event.get("requestContext", {})
                domain_name = request_context.get("domainName")
                stage = request_context.get("stage")
                
                if domain_name and stage:
                    cls._ws_manager.send_error_to_connection(
                        connection_id=connection_id,
                        error_message="Queue not configured",
                        domain_name=domain_name,
                        stage=stage
                    )
                return {"statusCode": 500}

            # Prepare message for queue
            queue_payload = {
                "session_id": session_id,
                "connection_id": connection_id,
                "message": body.get("message", ""),
                "metadata": body.get("metadata", {}),
                "websocket": True  # Flag to indicate WebSocket origin
            }

            # Send to SQS queue
            response = cls._sqs.send_message(
                QueueUrl=cls._input_queue_url,
                MessageBody=json.dumps(queue_payload),
                MessageGroupId=session_id,
                MessageDeduplicationId=str(uuid.uuid4()),
            )

            cls._log.info(f"Queued WebSocket message from {connection_id} (session: {session_id})")
            
            # Send acknowledgment to client using WebSocket manager
            request_context = event.get("requestContext", {})
            domain_name = request_context.get("domainName")
            stage = request_context.get("stage")
            
            if domain_name and stage:
                ack_message = cls._ws_manager.create_websocket_message(
                    message_type="queued",
                    session_id=session_id,
                    message_id=response.get("MessageId"),
                    status="processing"
                )
                
                cls._ws_manager.send_message_to_connection(
                    connection_id=connection_id,
                    message=ack_message,
                    domain_name=domain_name,
                    stage=stage
                )

            return {"statusCode": 200}

        except Exception as e:
            cls._log.error(f"Chat message error: {e}\n{traceback.format_exc()}")
            request_context = event.get("requestContext", {})
            domain_name = request_context.get("domainName")
            stage = request_context.get("stage")
            connection_id = event["requestContext"]["connectionId"]
            
            if domain_name and stage:
                cls._ws_manager.send_error_to_connection(
                    connection_id=connection_id,
                    error_message=f"Failed to process message: {str(e)}",
                    domain_name=domain_name,
                    stage=stage
                )
            return {"statusCode": 500}
    @classmethod
    def send_message_to_session_connections(cls, session_id: str, message: Dict[str, Any], 
                               domain_name: str, stage: str) -> bool:
        """
        Send a message to all connections for a given session.
        This method is called from queue consumers to push responses back to WebSocket clients.
        :param session_id: Session ID
        :param message: Message to send
        :param domain_name: API Gateway domain name
        :param stage: API Gateway stage
        :return: True if sent successfully, False otherwise
        """
        success, successful_sends, total_connections = cls._ws_manager.send_message_to_all_session_connections(
            session_id, message, domain_name, stage
        )
        
        cls._log.info(f"Sent message to {successful_sends}/{total_connections} connections for session {session_id}")
        return success