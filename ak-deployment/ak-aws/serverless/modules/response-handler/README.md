# Response Handler Module

This module creates the response handler Lambda that consumes output-queue messages and writes response data to the configured response store.

This is an internal submodule used by the root serverless stack in `state.tf`; the example below shows wiring, not an independent deployment entrypoint.

## What It Does

- Creates the response handler Lambda and execution role
- Attaches SQS receive permissions for the output queue
- Optionally grants DynamoDB response-store access
- Injects response-store and queue-related environment variables
- Supports `LocalZip`, `S3Zip`, and `Image` deployment modes
- Creates the SQS event source mapping for the output queue

## Example Wiring

```hcl
module "response_handler" {
  source = "./modules/response-handler"

  product_alias = "agent-kernel"
  env_alias     = "dev"
  region        = "us-east-1"

  response_handler = {
    function_name = "response-handler"
    handler_path  = "response_handler.handler"
    module_name   = "scalable-openai-response-handler"
    package_type  = "LocalZip"
    package_path  = "${path.module}/dist/response-handler.zip"
  }

  queue_config = {
    output_queue_arn = module.queues.output_queue_arn
  }

  response_store_dynamodb = {
    table_name = module.response_store.table_name
    table_arn  = module.response_store.table_arn
  }
  
  execution_mode = "async"
}
```

## Inputs

| Name | Description |
|------|-------------|
| `product_alias` | Product alias used in resource names |
| `env_alias` | Environment alias |
| `region` | AWS region for S3 path construction |
| `module_type` | Runtime type, `python` or `nodejs` |
| `source_bucket` | S3 bucket used for S3 ZIP deployment |
| `docker_image_uri` | Image URI when `response_handler.package_type = "Image"` |
| `is_production` | Enables code signing for production S3 ZIP deployments |
| `lambda_signer_profile_name` | AWS Signer profile name |
| `lambda_signing_config_arn` | Optional Lambda code signing config ARN |
| `response_handler` | Nested Lambda configuration object |
| `response_store_redis` | Redis response store configuration |
| `response_store_dynamodb` | DynamoDB response store configuration |
| `queue_config` | Output queue ARN and batch settings |
| `subnet_ids` | VPC subnet IDs |
| `security_group_id` | Optional security group ID to reuse |
| `lambda_kms_key_arn` | Lambda encryption key ARN |
| `cloudwatch_kms_key_arn` | CloudWatch log encryption key ARN |
| `execution_mode` | Execution mode for the serverless module (`sync` or `async`) |
| `websocket_connections_dynamodb` | DynamoDB configuration for websocket connections table |
| `websocket_api_execution_arn` | Execution ARN of the WebSocket API Gateway |

## Response Handler Object Structure

| Field | Description | Type | Default | Required |
|-------|-------------|------|---------|----------|
| `function_name` | Response handler Lambda function name | `string` | `"response-handler"` | no |
| `function_description` | Response handler Lambda description | `string` | `"Response handler Lambda for processing SQS messages and storing responses"` | no |
| `timeout` | Response handler Lambda timeout in seconds | `number` | `30` | no |
| `memory_size` | Response handler Lambda memory size in MB | `number` | `256` | no |
| `handler_path` | Response handler Lambda handler path | `string` | `"response_handler.handler"` | no |
| `module_name` | Response-handler artifact module name | `string` | `"response-handler"` | no |
| `package_path` | Response handler deployment package path | `string` | n/a | yes |
| `package_type` | Response handler deployment type (`LocalZip`, `S3Zip`, or `Image`) | `string` | `"LocalZip"` | no |
| `layers` | List of Lambda layer ARNs to attach | `list(string)` | `[]` | no |
| `environment_variables` | Environment variables for the response handler | `map(string)` | `{}` | no |

## Injected Environment Variables

- `AK_EXECUTION__RESPONSE_STORE__REDIS__URL`
- `AK_EXECUTION__RESPONSE_STORE__DYNAMODB__TABLE_NAME`
- `AK_EXECUTION__QUEUES__OUTPUT__MAX_RECEIVE_COUNT`

## Outputs

| Name | Description |
|------|-------------|
| `response_handler_lambda_function_arn` | ARN of the response handler Lambda |
| `response_handler_lambda_function_name` | Name of the response handler Lambda |
| `response_handler_lambda_function_invoke_arn` | Invoke ARN of the response handler Lambda |
| `response_handler_event_source_mapping_uuid` | UUID of the SQS event source mapping |

## Notes

- The response handler package is expected to be built before Terraform runs.
- When a DynamoDB response store is provided, the module grants read/write access to the configured table.