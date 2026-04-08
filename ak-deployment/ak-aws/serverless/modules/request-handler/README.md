# Request Handler Module

This module creates the request handler Lambda used by the serverless API path. It is responsible for the public request entrypoint and can optionally send work to the input queue when scalable mode is enabled.

This is an internal submodule used by the root serverless stack in `state.tf`; the example below shows wiring, not an independent deployment entrypoint.

## What It Does

- Creates the request handler Lambda and execution role
- Supports ZIP, S3 ZIP, and container image deployment modes
- Adds optional DynamoDB and Redis permissions for agent memory and response storage
- Injects execution and session environment variables when the relevant inputs are present
- Attaches SQS send permissions when `queue_mode = true`
- Passes through event source mapping configuration to the Lambda module

## Example Wiring

```hcl
module "request_handler" {
  source = "./modules/request-handler"

  product_alias  = "agent-kernel"
  env_alias      = "dev"
  region         = "us-east-1"
  module_name    = "scalable-openai"
  function_name  = "request-handler"
  function_description = "Public API request handler"
  handler_path   = "app.lambda_handler"
  package_path   = "${path.module}/dist/request-handler.zip"

  queue_mode  = true
  input_queue_arn = module.queues.input_queue_arn
  input_queue_url = module.queues.input_queue_url
  vpc_id         = module.vpc.vpc_id
  subnet_ids     = module.vpc.private_subnet_ids
}
```

## Inputs

| Name | Description |
|------|-------------|
| `product_alias` | Product alias used in resource names |
| `env_alias` | Environment alias |
| `region` | AWS region |
| `module_type` | Runtime type, `python` or `nodejs` |
| `module_name` | Module name used in resource names |
| `function_name` | Lambda function name suffix |
| `function_description` | Lambda function description |
| `handler_path` | Lambda handler path |
| `package_path` | Local package path or S3 ZIP URI |
| `package_type` | Deployment type (`LocalZip`, `S3Zip`, or `Image`) |
| `queue_mode` | Enables SQS integration and queue-based execution |
| `event_source_mapping` | Optional event source mapping settings |
| `environment_variables` | Extra environment variables |
| `timeout` | Lambda timeout |
| `memory_size` | Lambda memory size |
| `source_bucket` | S3 bucket used for S3 ZIP deployment |
| `input_queue_arn` | Input queue ARN used for SQS permissions |
| `input_queue_url` | Input queue URL injected into the environment |
| `redis_url` | Redis URL injected into the environment |
| `response_store_redis` | Redis response store configuration |
| `response_store_dynamodb` | DynamoDB response store configuration |
| `vpc_id` | VPC ID |
| `subnet_ids` | Private subnet IDs |
| `dynamodb_memory_table_arn` | Agent memory table ARN |
| `dynamodb_multimodal_memory_table_arn` | Multimodal memory table ARN |
| `lambda_signing_config_arn` | Optional code signing config ARN |
| `docker_image_uri` | Image URI when `package_type = "Image"` |

## Injected Environment Variables

The module adds these environment variables when the corresponding inputs are present:

- `API_BASE_PATH`
- `API_VERSION`
- `AGENT_ENDPOINT`
- `AK_SESSION__REDIS__URL`
- `AK_SESSION__DYNAMODB__TABLE_NAME`
- `AK_MULTIMODAL__DYNAMODB__TABLE_NAME`
- `AK_EXECUTION__RESPONSE_STORE__REDIS__URL`
- `AK_EXECUTION__RESPONSE_STORE__DYNAMODB__TABLE_NAME`
- `AK_EXECUTION__QUEUES__INPUT__URL`

## Outputs

| Name | Description |
|------|-------------|
| `lambda_function_arn` | ARN of the request handler Lambda |
| `lambda_function_name` | Name of the request handler Lambda |
| `lambda_function_invoke_arn` | Invoke ARN of the request handler Lambda |
| `lambda_role_arn` | IAM role ARN used by the Lambda |
| `lambda_security_group_id` | Security group ID used by the Lambda |

## Notes

- When `queue_mode = true`, the module creates SQS send permissions for the input queue.
- When `package_type = "S3Zip"`, the module expects the deployment package to already exist in S3.