# SQS Module

This module creates AWS SQS FIFO queues with dead-letter queue (DLQ) support using the [terraform-aws-modules/sqs](https://github.com/terraform-aws-modules/terraform-aws-sqs) module.

## Features

- **FIFO Queues**: Guarantees message ordering and exactly-once processing
- **Dead Letter Queue**: Automatically created for handling failed messages
- **Content-Based Deduplication**: Prevents duplicate messages within the deduplication window
- **Encryption**: Supports both SQS-managed and customer-managed KMS encryption
- **Access Control**: Built-in IAM policies for producers and consumers
- **Throughput Configuration**: Supports both per-queue and per-message-group throughput limits

## Usage

### Basic Example

```hcl
module "agent_queue" {
  source = "./modules/sqs"

  product_alias = "agent-kernel"
  env_alias     = "dev"
  module_name   = "chat"
  queue_name    = "messages"
  region        = "us-east-1"

  # Producer and consumer ARNs
  producer_arns      = [aws_lambda_function.producer.role_arn]
  consumer_role_arns = [aws_iam_role.consumer.arn]

  tags = {
    Environment = "development"
    Team        = "platform"
  }
}
```

### With Custom KMS Encryption

```hcl
module "secure_queue" {
  source = "./modules/sqs"

  product_alias = "agent-kernel"
  env_alias     = "prod"
  module_name   = "payments"
  queue_name    = "transactions"
  region        = "us-east-1"

  # Enable custom KMS encryption
  sqs_managed_sse_enabled = false
  kms_master_key_id       = aws_kms_key.sqs.arn

  producer_arns      = [aws_lambda_function.producer.role_arn]
  consumer_role_arns = [aws_iam_role.consumer.arn]

  tags = {
    Environment = "production"
    Compliance  = "pci-dss"
  }
}
```

### With Custom Throughput Settings

```hcl
module "chat_queue" {
  source = "./modules/sqs"

  product_alias = "chat-app"
  env_alias     = "prod"
  module_name   = "chat"
  queue_name    = "messages"
  region        = "us-east-1"

  # Per message group throughput for chat threads
  fifo_throughput_limit = "perQueueGroup"
  
  # Deduplication per thread (MessageGroupId = thread_id)
  deduplication_scope = "messageGroup"

  producer_arns      = [aws_lambda_function.producer.role_arn]
  consumer_role_arns = [aws_iam_role.consumer.arn]

  tags = {
    Environment = "production"
    Application = "chat"
  }
}
```

## Inputs

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|:--------:|
| `product_alias` | Product alias | `string` | - | yes |
| `env_alias` | Environment alias | `string` | - | yes |
| `module_name` | Module name for queue identification (e.g., 'chat', 'notifications', 'orders') | `string` | - | yes |
| `queue_name` | Queue name suffix (e.g., 'messages', 'events', 'requests') | `string` | - | yes |
| `region` | AWS region | `string` | - | yes |
| `product_display_name` | Product display name | `string` | - | yes |
| `is_production` | Whether this is a production environment | `bool` | - | yes |
| `max_message_size` | Maximum message size in bytes | `number` | `262144` | no |
| `message_retention_seconds` | How long messages remain in the queue | `number` | `3600` | no |
| `visibility_timeout_seconds` | Visibility timeout for messages | `number` | `30` | no |
| `max_receive_count` | Number of times a message can be received before being sent to DLQ | `number` | `3` | no |
| `dlq_message_retention_seconds` | How long messages remain in DLQ | `number` | `3600` | no |
| `fifo_throughput_limit` | FIFO throughput limit: 'perQueueGroup' or 'perQueue' | `string` | `"perQueueGroup"` | no |
| `content_based_deduplication` | Enable content-based deduplication | `bool` | `false` | no |
| `deduplication_scope` | Deduplication scope: 'queue' or 'messageGroup' | `string` | `"messageGroup"` | no |
| `sqs_managed_sse_enabled` | Enable SQS-managed server-side encryption (SSE) | `bool` | `true` | no |
| `kms_master_key_id` | The ID of a customer master key (CMK) for Amazon SQS | `string` | `null` | no |
| `kms_data_key_reuse_period_seconds` | Length of time for which Amazon SQS can reuse a data key | `number` | `300` | no |
| `enable_producer_access` | Enable IAM policy for producers | `bool` | `true` | no |
| `producer_arns` | ARNs of producers allowed to send messages | `list(string)` | `[]` | no |
| `enable_consumer_access` | Enable IAM policy for consumers | `bool` | `true` | no |
| `consumer_role_arns` | ARNs of consumer roles allowed to receive messages | `list(string)` | `[]` | no |
| `tags` | A map of tags to add | `map(string)` | `{}` | no |

## Outputs

| Name | Description |
|------|-------------|
| `queue_url` | URL of the main SQS FIFO queue |
| `queue_arn` | ARN of the main SQS FIFO queue |
| `queue_name` | Name of the main SQS FIFO queue |
| `queue_id` | ID of the main SQS FIFO queue |
| `dlq_url` | URL of the dead letter queue |
| `dlq_arn` | ARN of the dead letter queue |
| `dlq_name` | Name of the dead letter queue |
| `dlq_id` | ID of the dead letter queue |

## Queue Naming

Queue names are automatically generated using the following pattern:

- **Main Queue**: `{product_alias}-{env_alias}-{module_name}-{queue_name}.fifo`
- **DLQ**: `{product_alias}-{env_alias}-{module_name}-{queue_name}-dlq.fifo`

Example: `agent-kernel-dev-chat-messages.fifo`

## Access Control

### Producer Access

Producers can send messages to the queue. The module automatically creates an IAM policy statement that allows specified producer ARNs to call `sqs:SendMessage`.

### Consumer Access

Consumers can receive and process messages. The module creates an IAM policy that allows specified consumer role ARNs to:
- `sqs:ReceiveMessage` - Receive messages from the queue
- `sqs:DeleteMessage` - Delete processed messages
- `sqs:ChangeMessageVisibility` - Extend visibility timeout if needed
- `sqs:GetQueueAttributes` - Read queue attributes

## Deduplication Scope

The `deduplication_scope` setting determines where deduplication applies:

### Queue-Level Deduplication (`queue`)
Deduplication applies across the entire queue. If the same message appears in any message group, it's considered a duplicate.

**Use case:** When you want to prevent identical messages across all groups (rare).

### Message Group-Level Deduplication (`messageGroup`)
Deduplication applies only within each message group. The same message in different groups are NOT duplicates.

**Use case:** Chat systems where `MessageGroupId = thread_id`. Each thread can have the same message without being rejected.

**Example:**
```
Thread 1 (alice-bob): "Hello" → Accepted
Thread 2 (charlie-dave): "Hello" → Accepted (different thread, not a duplicate)
Thread 1 (alice-bob): "Hello" → Rejected (duplicate within same thread)
```

## Content-Based Deduplication

By default, `content_based_deduplication` is **disabled** for chat systems. Here's why:

### How Content-Based Deduplication Works

When enabled, AWS generates a deduplication ID from the message content hash. Messages with identical content within a 5-minute window are rejected:

```
Thread 1 (alice-bob):
├─ Message 1: "Hello" (10:00:00) → Accepted
├─ Message 2: "Hello" (10:00:05) → REJECTED (same content within 5 minutes)
├─ Message 3: "Hello" (10:05:30) → Accepted (outside 5-minute window)
└─ Message 4: "Hi there" (10:00:10) → Accepted (different content)
```

### For Chat Systems: Use Explicit Deduplication IDs

For chat applications, disable content-based deduplication and use explicit `MessageDeduplicationId` in your application:

```python
import uuid
import json

message = {
    'MessageGroupId': 'thread-123',
    'MessageDeduplicationId': str(uuid.uuid4()),  # Unique ID per message
    'MessageBody': json.dumps({
        'content': 'Hello',
        'sender': 'alice',
        'timestamp': '2026-03-11T10:00:00Z'
    })
}

sqs.send_message(**message)
```

This way:
- Users can send identical messages multiple times in the same thread
- Deduplication only prevents the exact same message (same ID) from being processed twice
- Protects against accidental retries or network duplicates

## Encryption

### SQS-Managed Encryption (Default - Recommended)

By default, the module enables SQS-managed server-side encryption (SSE-SQS) with AWS-managed keys. This provides:
- Encryption at rest using AES-256 algorithm
- No key management overhead
- Automatic key rotation by AWS
- No additional cost

This is the recommended approach for most use cases and is enabled by default.

### Customer-Managed KMS Encryption (Optional)

For sensitive data or compliance requirements (e.g., PCI-DSS, HIPAA), you can use a customer-managed KMS key:

```hcl
module "secure_queue" {
  source = "./modules/sqs"
  
  # ... other configuration ...
  
  sqs_managed_sse_enabled = false
  kms_master_key_id       = aws_kms_key.sqs.arn
  kms_data_key_reuse_period_seconds = 300
}
```

**Important**: When using customer-managed KMS keys, ensure that:
1. The KMS key policy allows the SQS service to use the key
2. Producer and consumer IAM roles have `kms:Decrypt`, `kms:Encrypt`, and `kms:GenerateDataKey*` permissions on the KMS key

**Note**: KMS encryption is optional and not required for basic security. Use it only when you need full control over encryption keys or have specific compliance requirements.

## Dead Letter Queue (DLQ)

The module automatically creates a DLQ that receives messages after they fail to be processed `max_receive_count` times (default: 3).

DLQ Configuration:
- **Retention**: 1 hour (3,600 seconds) by default
- **FIFO**: Enabled to match the main queue
- **Deduplication**: Content-based deduplication enabled

Messages in the DLQ can be inspected for debugging or processed by a separate recovery job.

## Best Practices

1. **Naming Convention**: Use descriptive suffixes that indicate the queue's purpose (e.g., 'requests', 'events', 'notifications')

2. **Visibility Timeout**: Set appropriately for your consumer processing time. Too short causes reprocessing; too long delays error detection.

3. **Message Retention**: Balance between operational needs and storage costs. Default is 1 hour for both main queue and DLQ.

4. **Access Control**: Always specify producer and consumer ARNs. Avoid using wildcards in IAM policies.

5. **Encryption**: Use customer-managed KMS keys for sensitive data or compliance requirements.

6. **Monitoring**: Set up CloudWatch alarms for:
   - Messages in DLQ
   - Queue depth
   - Message age

7. **Testing**: Test DLQ behavior by intentionally failing message processing to ensure proper error handling.

## Migration from Raw Resources

If you're migrating from raw `aws_sqs_queue` resources, the module provides the same functionality with better maintainability:

**Before:**
```hcl
resource "aws_sqs_queue" "main" {
  name = "my-queue.fifo"
  fifo_queue = true
  # ... many more attributes ...
}
```

**After:**
```hcl
module "main" {
  source = "./modules/sqs"
  
  product_alias = "my-product"
  env_alias     = "dev"
  queue_suffix  = "queue"
  # ... configuration ...
}
```

## References

- [terraform-aws-modules/sqs](https://github.com/terraform-aws-modules/terraform-aws-sqs)
- [AWS SQS Documentation](https://docs.aws.amazon.com/sqs/)
- [AWS SQS FIFO Queues](https://docs.aws.amazon.com/sqs/latest/dg/FIFO-queues.html)
