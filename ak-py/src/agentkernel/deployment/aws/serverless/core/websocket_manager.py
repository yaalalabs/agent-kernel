"""
WebSocket Manager for AWS Lambda WebSocket operations.

This module provides a centralized WebSocket management utility that handles:
- Connection lifecycle (connect/disconnect)
- Message sending to sessions and individual connections
- Connection table operations
- Stale connection cleanup
- API Gateway Management API interactions
"""

import logging
import json
from typing import Any, Dict, List, Optional, Tuple

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from agentkernel.core.config import AKConfig


class WebSocketManager:
    """
    Centralized WebSocket management utility for AWS Lambda functions.
    
    Handles all WebSocket-related operations including connection management,
    message sending, and DynamoDB table operations.
    """
    
    def __init__(self, logger_name: str = "ak.aws.websocket"):
        """
        Initialize WebSocket manager.
        
        :param logger_name: Logger name for this instance
        """
        self._log = logging.getLogger(logger_name)
        self._config = AKConfig.get()
        self._connection_table_name = self._config.execution.websocket_connection_table
        
        # AWS clients
        self._dynamodb = boto3.resource("dynamodb")
        self._connection_table = self._dynamodb.Table(self._connection_table_name) if self._connection_table_name else None
        
        if not self._connection_table_name:
            self._log.warning("websocket_connection_table not configured in AKConfig")
    
    def get_apigateway_management_client(self, domain_name: str, stage: str):
        """
        Create API Gateway Management client for WebSocket operations.
        
        :param domain_name: API Gateway domain name
        :param stage: API Gateway stage
        :return: API Gateway Management client
        :raises ValueError: If domain_name or stage is missing
        """
        if not domain_name or not stage:
            raise ValueError("Missing domain_name or stage for WebSocket communication")
        
        endpoint_url = f"https://{domain_name}/{stage}"
        return boto3.client("apigatewaymanagementapi", endpoint_url=endpoint_url)
    
    def get_apigateway_management_client_from_event(self, event: Dict[str, Any]):
        """
        Create API Gateway Management client from WebSocket event.
        
        :param event: API Gateway WebSocket event
        :return: API Gateway Management client
        :raises ValueError: If domain_name or stage is missing in event
        """
        request_context = event.get("requestContext", {})
        domain_name = request_context.get("domainName")
        stage = request_context.get("stage")
        
        return self.get_apigateway_management_client(domain_name, stage)
    
    def store_connection(self, session_id: str, connection_id: str, metadata: Optional[Dict[str, Any]] = None) -> bool:
        """
        Store a WebSocket connection in the connection table.
        
        :param session_id: Session ID
        :param connection_id: WebSocket connection ID
        :param metadata: Optional additional metadata to store
        :return: True if stored successfully, False otherwise
        """
        try:
            if not self._connection_table:
                raise ValueError("websocket_connection_table not configured")
            
            import time
            item = {
                "session_id": session_id,
                "connection_id": connection_id,
                "connected_at": int(time.time()*1000),
            }
            
            if metadata:
                item.update(metadata)
            
            self._connection_table.put_item(Item=item)
            self._log.info(f"Stored connection {connection_id} for session {session_id}")
            return True
            
        except Exception as e:
            self._log.error(f"Failed to store connection {connection_id}: {e}")
            return False
    
    def remove_connection(self, session_id: str, connection_id: str) -> bool:
        """
        Remove a WebSocket connection from the connection table.
        
        :param session_id: Session ID
        :param connection_id: WebSocket connection ID
        :return: True if removed successfully, False otherwise
        """
        try:
            if not self._connection_table:
                raise ValueError("websocket_connection_table not configured")
            
            self._connection_table.delete_item(
                Key={
                    "session_id": session_id,
                    "connection_id": connection_id
                }
            )
            self._log.info(f"Removed connection {connection_id} for session {session_id}")
            return True
            
        except Exception as e:
            self._log.error(f"Failed to remove connection {connection_id}: {e}")
            return False
    
    def get_session_connections(self, session_id: str) -> List[Dict[str, Any]]:
        """
        Get all active connections for a session.
        
        :param session_id: Session ID
        :return: List of connection items
        """
        try:
            if not self._connection_table:
                raise ValueError("websocket_connection_table not configured")
            
            response = self._connection_table.query(
                KeyConditionExpression=Key("session_id").eq(session_id)
            )
            
            connections = response.get("Items", [])
            self._log.debug(f"Found {len(connections)} connections for session {session_id}")
            return connections
            
        except Exception as e:
            self._log.error(f"Failed to get connections for session {session_id}: {e}")
            return []
    
    def get_session_id_from_connection(self, connection_id: str) -> Optional[str]:
        """
        Get session_id for a given connection_id.
        
        :param connection_id: WebSocket connection ID
        :return: Session ID if found, None otherwise
        """
        try:
            if not self._connection_table:
                raise ValueError("websocket_connection_table not configured")
            
            # Try GSI first (if available)
            try:
                response = self._connection_table.query(
                    IndexName="connection_id-index",
                    KeyConditionExpression=Key("connection_id").eq(connection_id)
                )
                
                items = response.get("Items", [])
                if items:
                    session_id = items[0]["session_id"]
                    self._log.debug(f"Found session {session_id} for connection {connection_id} (GSI)")
                    return session_id
                    
            except ClientError as e:
                if e.response["Error"]["Code"] == "ResourceNotFoundException":
                    self._log.debug("GSI 'connection_id-index' not found, using scan fallback")
                    # Fallback to scan
                    response = self._connection_table.scan(
                        FilterExpression=Key("connection_id").eq(connection_id)
                    )
                    
                    items = response.get("Items", [])
                    if items:
                        session_id = items[0]["session_id"]
                        self._log.debug(f"Found session {session_id} for connection {connection_id} (scan)")
                        return session_id
                else:
                    raise
                    
            return None
            
        except Exception as e:
            self._log.error(f"Error getting session_id for connection {connection_id}: {e}")
            return None
    
    def remove_connection_by_id(self, connection_id: str) -> bool:
        """
        Remove a connection by connection_id (finds session_id automatically).
        
        :param connection_id: WebSocket connection ID
        :return: True if removed successfully, False otherwise
        """
        try:
            session_id = self.get_session_id_from_connection(connection_id)
            if session_id:
                return self.remove_connection(session_id, connection_id)
            else:
                self._log.warning(f"Could not find session for connection {connection_id}")
                return False
                
        except Exception as e:
            self._log.error(f"Failed to remove connection {connection_id}: {e}")
            return False
    
    def send_message_to_connection(self, connection_id: str, message: Dict[str, Any], 
                                  domain_name: str, stage: str) -> bool:
        """
        Send a message to a specific WebSocket connection.
        
        :param connection_id: WebSocket connection ID
        :param message: Message to send
        :param domain_name: API Gateway domain name
        :param stage: API Gateway stage
        :return: True if sent successfully, False otherwise
        """
        try:
            apigateway_client = self.get_apigateway_management_client(domain_name, stage)
            
            apigateway_client.post_to_connection(
                ConnectionId=connection_id,
                Data=json.dumps(message)
            )
            
            self._log.debug(f"Sent message to connection {connection_id}")
            return True
            
        except apigateway_client.exceptions.GoneException:
            self._log.info(f"Connection {connection_id} is stale")
            return False
            
        except Exception as e:
            self._log.error(f"Failed to send message to connection {connection_id}: {e}")
            return False
    
    def send_message_to_all_session_connections(self, session_id: str, message: Dict[str, Any], 
                               domain_name: str, stage: str, 
                               cleanup_stale: bool = True) -> Tuple[bool, int, int]:
        """
        Send a message to all connections for a given session.
        
        :param session_id: Session ID
        :param message: Message to send
        :param domain_name: API Gateway domain name
        :param stage: API Gateway stage
        :param cleanup_stale: Whether to automatically clean up stale connections
        :return: Tuple of (success, successful_sends, total_connections)
        """
        try:
            connections = self.get_session_connections(session_id)
            if not connections:
                self._log.warning(f"No active connections found for session {session_id}")
                return False, 0, 0
            
            apigateway_client = self.get_apigateway_management_client(domain_name, stage)
            
            successful_sends = 0
            stale_connections = []
            
            for connection in connections:
                connection_id = connection["connection_id"]
                try:
                    apigateway_client.post_to_connection(
                        ConnectionId=connection_id,
                        Data=json.dumps(message)
                    )
                    successful_sends += 1
                    self._log.debug(f"Sent message to connection {connection_id}")
                    
                except apigateway_client.exceptions.GoneException:
                    # Connection is stale, mark for removal
                    stale_connections.append(connection)
                    self._log.info(f"Connection {connection_id} is stale, will remove")
                    
                except Exception as e:
                    self._log.error(f"Failed to send message to connection {connection_id}: {e}")
            
            # Clean up stale connections if requested
            if cleanup_stale and stale_connections:
                self._cleanup_stale_connections(session_id, stale_connections)
            
            total_connections = len(connections)
            success = successful_sends > 0
            
            self._log.info(f"Sent message to {successful_sends}/{total_connections} connections for session {session_id}")
            return success, successful_sends, total_connections
            
        except Exception as e:
            self._log.error(f"Error sending message to session {session_id}: {e}")
            return False, 0, 0
    
    def _cleanup_stale_connections(self, session_id: str, stale_connections: List[Dict[str, Any]]):
        """
        Clean up stale connections from the connection table.
        
        :param session_id: Session ID
        :param stale_connections: List of stale connection items
        """
        for stale_connection in stale_connections:
            try:
                self.remove_connection(session_id, stale_connection["connection_id"])
            except Exception as e:
                self._log.error(f"Failed to remove stale connection {stale_connection['connection_id']}: {e}")
    
    def send_error_to_connection(self, connection_id: str, error_message: str, 
                                domain_name: str, stage: str, 
                                error_type: str = "error") -> bool:
        """
        Send an error message to a specific WebSocket connection.
        
        :param connection_id: WebSocket connection ID
        :param error_message: Error message to send
        :param domain_name: API Gateway domain name
        :param stage: API Gateway stage
        :param error_type: Type of error message
        :return: True if sent successfully, False otherwise
        """
        error_response = {
            "type": error_type,
            "message": error_message
        }
        
        return self.send_message_to_connection(connection_id, error_response, domain_name, stage)
    
    def send_error_to_all_session_connections(self, session_id: str, error_message: str, 
                             domain_name: str, stage: str, 
                             error_type: str = "error") -> Tuple[bool, int, int]:
        """
        Send an error message to all connections for a session.
        
        :param session_id: Session ID
        :param error_message: Error message to send
        :param domain_name: API Gateway domain name
        :param stage: API Gateway stage
        :param error_type: Type of error message
        :return: Tuple of (success, successful_sends, total_connections)
        """
        error_response = {
            "type": error_type,
            "message": error_message
        }
        
        return self.send_message_to_all_session_connections(session_id, error_response, domain_name, stage)
    
    def get_websocket_details_from_message(self, message_data: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
        """
        Extract WebSocket connection details from message data.
        Falls back to environment variables if not found in message.
        
        :param message_data: Message data dictionary
        :return: Tuple of (domain_name, stage)
        """
        import os
        
        domain_name = message_data.get("domain_name")
        stage = message_data.get("stage")
        
        # Fallback to environment variables
        if not domain_name:
            domain_name = os.environ.get("WEBSOCKET_DOMAIN_NAME")
        if not stage:
            stage = os.environ.get("WEBSOCKET_STAGE", "prod")
        
        return domain_name, stage
    
    def create_websocket_message(self, message_type: str, session_id: str, 
                                message_id: Optional[str] = None, 
                                body: Optional[Any] = None, 
                                timestamp: Optional[str] = None,
                                **kwargs) -> Dict[str, Any]:
        """
        Create a standardized WebSocket message.
        
        :param message_type: Type of message (e.g., 'response', 'error', 'queued')
        :param session_id: Session ID
        :param message_id: Optional message ID
        :param body: Optional message body
        :param timestamp: Optional timestamp
        :param kwargs: Additional fields to include in message
        :return: Formatted WebSocket message
        """
        message = {
            "type": message_type,
            "session_id": session_id
        }
        
        if message_id is not None:
            message["message_id"] = message_id
        if body is not None:
            message["body"] = body
        if timestamp is not None:
            message["timestamp"] = timestamp
        
        # Add any additional fields
        message.update(kwargs)
        
        return message