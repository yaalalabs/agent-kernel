# WebSocket API Gateway Module

This module creates a WebSocket API Gateway for real-time bidirectional communication and wires it to two Lambda functions: a connection handler for connection lifecycle events and a routes handler for message routing.

This module uses:
- `terraform-aws-modules/apigateway-v2/aws` for the WebSocket API Gateway

This is an internal submodule used by the root serverless stack in `state.tf`; the example below shows wiring, not an independent deployment entrypoint.

## What It Does

- Creates a WebSocket API with route selection based on `request.body.route`
- Configures predefined routes: `$connect`, `$disconnect`, `$default`
- Supports configurable chat route (default: `chat`) and additional custom routes
- Uses a connection handler Lambda for `$connect` and `$disconnect` routes
- Uses a routes handler Lambda for `$default` and custom routes (e.g., `chat`, custom routes)
- Creates CloudWatch log groups and stage logging
- Configures Lambda permissions for both Lambda functions

## Example Wiring

```hcl
module "websocket_api_gateway" {
  source = "./modules/websocket-api-gateway"

  region              = "us-east-1"
  product_alias       = "agent-kernel"
  env_alias           = "dev"
  product_display_name = "Agent Kernel"
  stage_name          = "prod"

  # Routes handler Lambda (for $default and custom routes like chat)
  route_handler_lambda_name    = module.websocket_routes_handler.lambda_function_name
  route_handler_lambda_invoke_arn = module.websocket_routes_handler.lambda_function_invoke_arn

  # Connection handler Lambda (for $connect and $disconnect routes)
  connection_handler_lambda_name = module.websocket_connection_handler.lambda_function_name
  connection_handler_lambda_invoke_arn = module.websocket_connection_handler.lambda_function_invoke_arn

  enable_data_trace          = false
  logging_level              = "ERROR"
  enable_detailed_metrics    = false
  cloudwatch_logs_retention_in_days = 90
}
```

## Inputs

| Name | Description |
|------|-------------|
| `region` | AWS region |
| `product_alias` | Product alias for naming |
| `env_alias` | Environment alias |
| `product_display_name` | Human-readable product name |
| `stage_name` | WebSocket API stage name |
| `route_handler_lambda_invoke_arn` | Routes handler Lambda function invoke ARN (for $default and custom routes) |
| `route_handler_lambda_name` | Routes handler Lambda function name |
| `connection_handler_lambda_invoke_arn` | Connection handler Lambda function invoke ARN (for $connect and $disconnect routes) |
| `connection_handler_lambda_name` | Connection handler Lambda function name |
| `enable_data_trace` | Enable data trace logging |
| `logging_level` | Logging level (ERROR, INFO, OFF) |
| `enable_detailed_metrics` | Enable detailed metrics |
| `cloudwatch_logs_retention_in_days` | CloudWatch logs retention period |
| `cloudwatch_kms_key_arn` | Optional CloudWatch log encryption key |
| `tags` | Resource tags |

## Outputs

| Name | Description |
|------|-------------|
| `websocket_api_endpoint_url` | WebSocket API endpoint URL |
| `websocket_api_id` | WebSocket API ID |
| `websocket_api_execution_arn` | WebSocket API execution ARN |
| `websocket_api_stage_name` | WebSocket API stage name |
| `websocket_api_stage_arn` | WebSocket API stage ARN |
| `websocket_cloudwatch_log_group_arn` | CloudWatch log group ARN |
| `websocket_cloudwatch_log_group_name` | CloudWatch log group name |

## Notes

- The WebSocket API uses `$request.body.route` for route selection
- The module uses a dual-lambda architecture:
  - **Connection handler Lambda**: Handles `$connect` and `$disconnect` routes for connection lifecycle management
  - **Routes handler Lambda**: Handles `$default` and custom routes (configurable chat route and additional custom routes) for message routing and processing
- Both Lambda functions use AWS_PROXY integration and receive route information in the event context
- Lambda permissions are configured for both Lambda functions to allow WebSocket API invocation
- Custom routes are configured at the parent serverless module level via `ws_chat_route` and `ws_routes` variables
- Route names must contain only alphanumeric characters, hyphens (-), and underscores (_)
