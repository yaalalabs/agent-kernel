# API Gateway Module

This module creates the REST API Gateway used by the serverless deployment and wires it to the request handler Lambda.

This is an internal submodule used by the root serverless stack in `state.tf`; the example below shows wiring, not an independent deployment entrypoint.

## What It Does

- Creates a regional REST API
- Builds `/api/{api_version}/{endpoint}` resources
- Supports nested endpoints up to three path segments
- Optionally configures a Lambda authorizer
- Creates CloudWatch log groups and stage logging

## Example Wiring

```hcl
module "api_gateway" {
  source = "./modules/api-gateway"

  region              = "us-east-1"
  product_alias       = "agent-kernel"
  env_alias           = "dev"
  product_display_name = "Agent Kernel"
  api_base_path       = "api"
  api_version         = "v1"
  agent_endpoint      = "chat"

  lambda_function_name    = module.request_handler.lambda_function_name
  lambda_function_invoke_arn = module.request_handler.lambda_function_invoke_arn

  endpoints = [
    { path = "chat", method = "POST" },
    { path = "health", method = "GET" }
  ]
}
```

## Inputs

| Name | Description |
|------|-------------|
| `region` | AWS region |
| `product_alias` | Product alias for naming |
| `env_alias` | Environment alias |
| `product_display_name` | Human-readable product name |
| `api_base_path` | Base path segment under the API root |
| `api_version` | Version segment under the base path |
| `agent_endpoint` | Primary agent endpoint path |
| `lambda_function_invoke_arn` | Request handler invoke ARN |
| `lambda_function_name` | Request handler Lambda name |
| `endpoints` | Additional REST endpoints |
| `authorizer` | Optional authorizer configuration |
| `create_authorizer` | Whether to create the authorizer |
| `cloudwatch_kms_key_arn` | Optional CloudWatch log encryption key |
| `tags` | Resource tags |

## Outputs

| Name | Description |
|------|-------------|
| `api_gateway_rest_api_id` | REST API ID |
| `api_gateway_execution_arn` | API execution ARN |
| `api_gateway_stage_name` | Stage name |
| `api_gateway_stage_invoke_url` | Stage invoke URL |
| `agent_invoke_url` | Full invoke URL for the agent endpoint |
| `api_gateway_deployment_id` | Deployment ID |
| `api_gateway_cloudwatch_log_group_arn` | CloudWatch log group ARN |
| `api_gateway_cloudwatch_log_group_name` | CloudWatch log group name |
| `api_gateway_authorizer_id` | Authorizer ID when enabled |

## Notes

- Endpoint paths are normalized into a maximum of three nested resource levels.
- When an authorizer is enabled, the API uses `CUSTOM` authorization for all methods.