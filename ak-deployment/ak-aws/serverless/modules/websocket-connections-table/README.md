# WebSocket Connections Table Module

This module creates a DynamoDB table to store WebSocket connection information for session management.

## Table Schema

- **Hash Key**: `session_id` (String) - The session identifier
- **Range Key**: `connection_id` (String) - The WebSocket connection identifier
- **GSI**: `connection_id-index` - Global Secondary Index for reverse lookups
- **TTL**: `ttl` attribute for automatic cleanup of stale connections

## Features

- Pay-per-request billing mode for cost optimization
- Global Secondary Index for efficient connection_id lookups
- TTL enabled for automatic cleanup of expired connections
- Proper IAM permissions for Lambda access

## Usage

This module is automatically included when `execution_mode = "async"` in the serverless deployment.

## Outputs

- `table_name` - Name of the DynamoDB table
- `table_arn` - ARN of the DynamoDB table
- `table_id` - ID of the DynamoDB table