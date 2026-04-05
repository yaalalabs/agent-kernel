# Response Handler Module

This module creates the response handler Lambda that consumes output-queue messages and writes response data to the configured response store.

This is an internal submodule used by the root serverless stack in `state.tf`; the example below shows wiring, not an independent deployment entrypoint.

## What It Does

- Creates the response handler Lambda and execution role
- Attaches SQS receive permissions for the output queue
- Optionally grants DynamoDB response-store access
- Injects response-store and queue-related environment variables
- Creates the SQS event source mapping for the output queue

## Example Wiring

```hcl
module "response_handler" {
  source = "./modules/response-handler"

  product_alias = "agent-kernel"
  env_alias     = "dev"
  module_name   = "scalable-openai"
  package_path  = "${path.module}/dist/response-handler.zip"

  response_handler = {
    function_name = "response-handler"
    handler_path  = "response_handler.handler"
  }

  queue_config = {
    output_queue_arn = module.queues.output_queue_arn
  }

  response_store_dynamodb = {
    table_name = module.response_store.table_name
    table_arn  = module.response_store.table_arn
  }
}
```

## Inputs

| Name | Description |
|------|-------------|
| `product_alias` | Product alias used in resource names |
| `env_alias` | Environment alias |
| `module_name` | Module name used in resource names |
| `package_path` | Local ZIP path for the response handler Lambda |
| `module_type` | Runtime type, `python` or `nodejs` |
| `package_type` | Deployment type, currently expected to be ZIP-based |
| `response_handler` | Nested Lambda configuration object |
| `response_store_redis` | Redis response store configuration |
| `response_store_dynamodb` | DynamoDB response store configuration |
| `queue_config` | Output queue ARN and batch settings |
| `subnet_ids` | VPC subnet IDs |
| `security_group_id` | Optional security group ID to reuse |
| `lambda_kms_key_arn` | Lambda encryption key ARN |
| `cloudwatch_kms_key_arn` | CloudWatch log encryption key ARN |

## Injected Environment Variables

- `AK_EXECUTION__RESPONSE_STORE__REDIS__URL`
- `AK_EXECUTION__RESPONSE_STORE__DYNAMODB__TABLE_NAME`
- `AK_EXECUTION__QUEUES__OUTPUT_QUEUE_MAX_RECEIVE_COUNT`

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