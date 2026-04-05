# SQS Module

This module creates a single AWS SQS queue with optional dead-letter queue support and separate producer and consumer access control. It wraps [terraform-aws-modules/sqs](https://github.com/terraform-aws-modules/terraform-aws-sqs) v5.2.1.

## Features

- Standard or FIFO queues
- Optional DLQ creation and redrive policy
- SQS-managed or customer-managed encryption
- Separate producer and consumer IAM policies
- FIFO tuning for content deduplication and throughput
- Queue naming based on product, environment, module, and queue name

## Usage

### Standard Queue

```hcl
module "processing_queue" {
  source = "yaalalabs/ak-common/aws//modules/sqs"

  product_alias        = "agent-kernel"
  env_alias            = "dev"
  module_name          = "processing"
  queue_name           = "requests"
  region               = "us-east-1"
  product_display_name = "Agent Kernel"
  is_production        = false

  fifo_queue                = false
  receive_wait_time_seconds = 20

  producer_arns      = [aws_lambda_function.producer.arn]
  consumer_role_arns = [aws_iam_role.consumer.arn]
}
```

### FIFO Queue With DLQ

```hcl
module "chat_queue" {
  source = "yaalalabs/ak-common/aws//modules/sqs"

  product_alias        = "agent-kernel"
  env_alias            = "prod"
  module_name          = "chat"
  queue_name           = "messages"
  region               = "us-east-1"
  product_display_name = "Agent Kernel"
  is_production        = true

  fifo_queue                  = true
  create_dlq                  = true
  content_based_deduplication = false
  deduplication_scope         = "messageGroup"
  fifo_throughput_limit       = "perMessageGroup"

  producer_arns      = [aws_lambda_function.chat_producer.arn]
  consumer_role_arns = [aws_iam_role.chat_consumer.arn]
}
```

## Inputs

### Required

| Name | Description | Type |
|------|-------------|------|
| `product_alias` | Product alias used in resource names | `string` |
| `env_alias` | Environment alias | `string` |
| `module_name` | Module name used in resource names | `string` |
| `queue_name` | Queue name suffix | `string` |
| `product_display_name` | Human-readable product name | `string` |
| `is_production` | Production environment flag | `bool` |

### Queue Settings

| Name | Description | Default |
|------|-------------|---------|
| `fifo_queue` | Create a FIFO queue | `false` |
| `create_dlq` | Create a dead-letter queue | `false` |
| `max_message_size` | Maximum message size in bytes | `null` |
| `message_retention_seconds` | Message retention period | `null` |
| `visibility_timeout_seconds` | Visibility timeout | `null` |
| `receive_wait_time_seconds` | Long polling wait time | `null` |
| `delay_seconds` | Delivery delay | `null` |
| `max_receive_count` | Number of receives before DLQ redrive | `5` |
| `dlq_message_retention_seconds` | DLQ retention period | `null` |

### FIFO Settings

| Name | Description | Default |
|------|-------------|---------|
| `content_based_deduplication` | Enable content-based deduplication | `null` |
| `deduplication_scope` | Deduplication scope | `null` |
| `fifo_throughput_limit` | FIFO throughput limit | `null` |

### Encryption and Access Control

| Name | Description | Default |
|------|-------------|---------|
| `sqs_managed_sse_enabled` | Use SQS-managed server-side encryption | `true` |
| `kms_master_key_id` | Customer-managed KMS key ARN or ID | `null` |
| `kms_data_key_reuse_period_seconds` | KMS data key reuse period | `null` |
| `enable_producer_access` | Create producer policy when producer ARNs are present | `true` |
| `producer_arns` | ARNs allowed to send messages | `[]` |
| `enable_consumer_access` | Create consumer policy when consumer role ARNs are present | `true` |
| `consumer_role_arns` | ARNs allowed to receive messages | `[]` |
| `tags` | Additional resource tags | `{}` |

## Outputs

| Name | Description |
|------|-------------|
| `queue_url` | URL of the main queue |
| `queue_arn` | ARN of the main queue |
| `queue_name` | Name of the main queue |
| `queue_id` | ID of the main queue |
| `dlq_url` | URL of the DLQ, when created |
| `dlq_arn` | ARN of the DLQ, when created |
| `dlq_name` | Name of the DLQ, when created |
| `dlq_id` | ID of the DLQ, when created |

## Notes

- Queue names are generated as `<product_alias>-<env_alias>-<module_name>-<queue_name>`.
- FIFO queues receive a `.fifo` suffix.
- Producer and consumer policies are only created when the corresponding ARN lists are non-empty.