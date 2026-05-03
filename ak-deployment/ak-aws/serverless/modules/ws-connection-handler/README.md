# WebSocket Connection Handler Module

This module creates a Lambda function to handle WebSocket `$connect` and `$disconnect` routes for Agent Kernel's async execution mode.

## Overview

The WebSocket connection handler is responsible for:
- Managing WebSocket connection lifecycle (`$connect` and `$disconnect` routes)
- Storing and removing connection metadata in DynamoDB
- Authentication during the `$connect` route (when integrated with an authorizer)

## Usage

```hcl
module "ws_connection_handler" {
  source = "./modules/ws-connection-handler"

  product_alias = "myapp"
  env_alias     = "prod"
  region        = "us-east-1"
  module_type   = "python"

  vpc_id            = module.vpc.vpc_id
  subnet_ids        = module.vpc.private_subnet_ids
  security_group_id = aws_security_group.lambda.id

  ws_connection_handler = {
    function_name        = "ws-connection-handler"
    function_description = "WebSocket connection handler for $connect and $disconnect"
    timeout              = 10
    memory_size          = 128
    handler_path         = "ws_connection_handler.handler"
    package_path         = "./path/to/ws_connection_handler.zip"
    environment_variables = {
      LOG_LEVEL = "INFO"
    }
  }

  websocket_connection_table_arn = module.websocket_api_gateway.websocket_connection_table_arn
}
```

## Requirements

- The Lambda function must be packaged as a LocalZip (package_path pointing to a local zip file)
- The handler must implement `$connect` and `$disconnect` route handling logic
- DynamoDB connection table must exist (created by `websocket-api-gateway` module)

## Inputs

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|----------|
| `product_alias` | Product alias for resource naming | `string` | n/a | yes |
| `env_alias` | Environment alias for resource naming | `string` | n/a | yes |
| `region` | AWS region | `string` | n/a | yes |
| `module_type` | Module type (python or nodejs) | `string` | `"python"` | no |
| `vpc_id` | VPC ID | `string` | `null` | no |
| `subnet_ids` | Subnet IDs for VPC deployment | `list(string)` | `[]` | no |
| `security_group_id` | Security group ID for Lambda | `string` | `""` | no |
| `module_name` | Module name | `string` | `"ws-connection-handler"` | no |
| `is_production` | Is production | `bool` | `false` | no |
| `lambda_kms_key_arn` | KMS key ARN for Lambda encryption | `string` | `null` | no |
| `cloudwatch_kms_key_arn` | KMS key ARN for CloudWatch logs encryption | `string` | `null` | no |
| `tags` | Tags to apply to resources | `map(string)` | `{}` | no |
| `ws_connection_handler` | Connection handler configuration | `object` | n/a | yes |
| `websocket_connection_table_arn` | DynamoDB connection table ARN | `string` | n/a | yes |

### ws_connection_handler Object

| Name | Description | Type | Default |
|------|-------------|------|---------|
| `function_name` | Lambda function name | `string` | `"ws-connection-handler"` |
| `function_description` | Lambda function description | `string` | `"WebSocket connection handler Lambda for $connect and $disconnect routes"` |
| `timeout` | Lambda timeout in seconds | `number` | `30` |
| `memory_size` | Lambda memory in MB | `number` | `256` |
| `handler_path` | Lambda handler path | `string` | `"ws_connection_handler.handler"` |
| `module_name` | Module name for resource naming | `string` | `"ws-connection-handler"` |
| `package_path` | Path to Lambda zip package | `string` | n/a (required) |
| `layers` | Lambda layers ARNs | `list(string)` | `[]` |
| `cloudwatch_logs_retention_in_days` | Log retention period | `number` | `90` |
| `environment_variables` | Environment variables | `map(string)` | `{}` |

## Outputs

| Name | Description |
|------|-------------|
| `ws_connection_handler_lambda_function_arn` | Lambda function ARN |
| `ws_connection_handler_lambda_function_name` | Lambda function name |
| `ws_connection_handler_lambda_function_invoke_arn` | Lambda invoke ARN |
| `ws_connection_handler_lambda_role_arn` | Lambda execution role ARN |
| `ws_connection_handler_lambda_role_name` | Lambda execution role name |
