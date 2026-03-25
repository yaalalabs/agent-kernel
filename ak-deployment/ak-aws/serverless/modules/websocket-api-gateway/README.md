# WebSocket API Gateway Module

This module creates an AWS API Gateway WebSocket API with the following routes:
- `$connect` - Handles WebSocket connection establishment
- `$disconnect` - Handles WebSocket disconnection
- `$default` - Handles unknown/default messages
- `chat` - Handles chat messages

## Features

- WebSocket API Gateway with regional endpoint
- CloudWatch logging with structured JSON format
- Lambda integration for all routes
- Configurable stage deployment
- Proper IAM permissions for Lambda invocation

## Usage

This module is automatically included when `execution_mode = "async"` in the serverless deployment.

## Outputs

- `websocket_api_id` - ID of the WebSocket API
- `websocket_api_endpoint` - WebSocket API endpoint URL
- `websocket_stage_invoke_url` - Full invoke URL for WebSocket connections
- `websocket_api_execution_arn` - Execution ARN for IAM permissions