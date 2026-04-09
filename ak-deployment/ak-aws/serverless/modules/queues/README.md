# Queues Module

This module creates the paired input and output queues used by the scalable serverless deployment. It is a thin wrapper around the shared [common SQS module](https://github.com/yaalalabs/agent-kernel/tree/develop/ak-deployment/ak-aws/common/modules/sqs/README.md).

This is an internal submodule used by the root serverless stack in `state.tf`; the example below shows wiring, not an independent deployment entrypoint.

## What It Does

- Creates an input queue and an output queue
- Reuses the same queue defaults for both queues
- Supports FIFO or standard queues through `queue_config`
- Propagates DLQ, encryption, and access control settings to both queues

## Example Wiring

```hcl
module "queues" {
  source = "./modules/queues"

  product_alias = "agent-kernel"
  env_alias     = "dev"
  module_name   = "scalable-openai"

  queue_config = {
    input_queue_name  = "input-queue"
    output_queue_name = "output-queue"
    fifo_queue        = true
  }
}
```

## Inputs

| Name | Description |
|------|-------------|
| `product_alias` | Product alias used in queue names |
| `env_alias` | Environment alias |
| `module_name` | Module name used in queue names |
| `tags` | Resource tags |
| `queue_config` | Nested configuration shared by both queues |

### `queue_config` Fields

| Name | Description | Default |
|------|-------------|---------|
| `input_queue_name` | Input queue suffix | `input-queue` |
| `output_queue_name` | Output queue suffix | `output-queue` |
| `input_queue_visibility_timeout` | Input queue visibility timeout | `60` |
| `input_queue_max_receive_count` | Input queue DLQ redrive count | `5` |
| `input_queue_message_retention_seconds` | Input queue retention | `1800` |
| `input_queue_max_message_size` | Input queue max message size | `262144` |
| `input_queue_receive_wait_time_seconds` | Input queue long polling time | `0` |
| `input_queue_delay_seconds` | Input queue delivery delay | `0` |
| `input_queue_create_dlq` | Create an input DLQ | `false` |
| `input_queue_dlq_message_retention_seconds` | Input DLQ retention | `1800` |
| `output_queue_visibility_timeout` | Output queue visibility timeout | `60` |
| `output_queue_max_receive_count` | Output queue DLQ redrive count | `5` |
| `output_queue_message_retention_seconds` | Output queue retention | `1800` |
| `output_queue_max_message_size` | Output queue max message size | `262144` |
| `output_queue_receive_wait_time_seconds` | Output queue long polling time | `0` |
| `output_queue_delay_seconds` | Output queue delivery delay | `0` |
| `output_queue_create_dlq` | Create an output DLQ | `false` |
| `output_queue_dlq_message_retention_seconds` | Output DLQ retention | `1800` |
| `fifo_queue` | Create FIFO queues | `true` |
| `sqs_managed_sse_enabled` | Use SQS-managed encryption | `true` |
| `kms_master_key_id` | Customer-managed KMS key ARN or ID | `null` |
| `kms_data_key_reuse_period_seconds` | KMS data key reuse period | `null` |
| `content_based_deduplication` | FIFO content-based deduplication | `false` |
| `fifo_throughput_limit` | FIFO throughput limit | `perMessageGroupId` |
| `deduplication_scope` | FIFO deduplication scope | `messageGroup` |
| `enable_producer_access` | Create producer policies when producer ARNs are present | `true` |
| `producer_arns` | Producer ARNs | `[]` |
| `enable_consumer_access` | Create consumer policies when consumer role ARNs are present | `true` |
| `consumer_role_arns` | Consumer role ARNs | `[]` |
| `batch_size` | Lambda event source batch size | `10` |
| `maximum_batching_window_in_seconds` | Lambda event source batching window | `0` |

## Outputs

| Name | Description |
|------|-------------|
| `input_queue_arn` | ARN of the input queue |
| `input_queue_url` | URL of the input queue |
| `input_queue_name` | Name of the input queue |
| `input_dlq_arn` | ARN of the input DLQ |
| `input_dlq_url` | URL of the input DLQ |
| `output_queue_arn` | ARN of the output queue |
| `output_queue_url` | URL of the output queue |
| `output_queue_name` | Name of the output queue |
| `output_dlq_arn` | ARN of the output DLQ |
| `output_dlq_url` | URL of the output DLQ |