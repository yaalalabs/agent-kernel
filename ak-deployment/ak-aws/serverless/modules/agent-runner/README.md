# Agent Runner Module

This module creates the worker Lambda that consumes messages from the input queue, processes work, and publishes results to the output queue.

This is an internal submodule used by the root serverless stack in `state.tf`; the example below shows wiring, not an independent deployment entrypoint.

## What It Does

- Creates the agent runner Lambda and IAM role
- Attaches basic, VPC, and SQS permissions
- Optionally grants DynamoDB access for agent memory tables
- Supports `LocalZip`, `S3Zip`, and `Image` deployment modes
- Creates an SQS event source mapping on the input queue

## Example Wiring

```hcl
module "agent_runner" {
  source = "./modules/agent-runner"

  product_alias = "agent-kernel"
  env_alias     = "dev"
  region        = "us-east-1"
  module_type   = "python"

  agent_runner = {
    function_name = "agent-runner"
    package_path  = "${path.module}/dist/agent-runner.zip"
    handler_path  = "agent_runner.handler"
  }

  queue_config = {
    input_queue_arn  = module.queues.input_queue_arn
    output_queue_arn = module.queues.output_queue_arn
    output_queue_url = module.queues.output_queue_url
  }

  subnet_ids = module.vpc.private_subnet_ids
}
```

## Inputs

| Name | Description |
|------|-------------|
| `product_alias` | Product alias used in resource names |
| `env_alias` | Environment alias |
| `region` | AWS region |
| `module_type` | Runtime type, `python` or `nodejs` |
| `agent_runner` | Nested configuration for the Lambda function |
| `queue_config` | Input/output queue wiring and batch settings |
| `subnet_ids` | Private subnet IDs for VPC attachment |
| `security_group_id` | Optional security group ID to reuse |
| `redis_url` | Redis URL injected into the function environment |
| `dynamodb_memory_table_arn` | Agent memory table ARN |
| `dynamodb_multimodal_memory_table_arn` | Multimodal memory table ARN |
| `lambda_kms_key_arn` | Lambda encryption key ARN |
| `cloudwatch_kms_key_arn` | CloudWatch log encryption key ARN |

## Agent Runner Environment Variables

The module injects the following values when present:

- `AK_SESSION__REDIS__URL`
- `AK_SESSION__DYNAMODB__TABLE_NAME`
- `AK_MULTIMODAL__DYNAMODB__TABLE_NAME`
- `AK_EXECUTION__QUEUES__INPUT__MAX_RECEIVE_COUNT`
- `AK_EXECUTION__QUEUES__OUTPUT__URL`

## Outputs

| Name | Description |
|------|-------------|
| `agent_runner_lambda_function_arn` | ARN of the Lambda function |
| `agent_runner_lambda_function_name` | Name of the Lambda function |
| `agent_runner_lambda_function_invoke_arn` | Invoke ARN of the Lambda function |
| `agent_runner_event_source_mapping_uuid` | UUID of the SQS event source mapping |