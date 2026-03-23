# SQS Module

This Terraform module creates AWS SQS queues (both FIFO and standard) with integrated dead-letter queue (DLQ) support and comprehensive access control. Built on top of the [terraform-aws-modules/sqs](https://github.com/terraform-aws-modules/terraform-aws-sqs) module v5.2.1.

## Features

- **FIFO and Standard Queues**: Supports both FIFO queues (with ordering guarantees) and standard queues (higher throughput)
- **Optional Dead Letter Queue**: Configurable DLQ creation with automatic redrive policy configuration
- **Content-Based Deduplication**: Configurable deduplication for FIFO queues with flexible scoping
- **Dual Encryption Support**: SQS-managed SSE (default) or customer-managed KMS encryption
- **Granular Access Control**: Separate IAM policies for producers and consumers with least-privilege access
- **FIFO Throughput Optimization**: Configurable throughput limits (per-queue or per-message-group)
- **Long Polling Support**: Configurable receive wait time for efficient message retrieval
- **Standardized Naming**: Consistent queue naming convention across environments

## Usage

### Basic Standard Queue Example

```hcl
### Basic Standard Queue Example

```hcl
module "processing_queue" {
  source = "./modules/sqs"

  product_alias         = "agent-kernel"
  env_alias            = "dev"
  module_name          = "processing"
  queue_name           = "requests"
  region               = "us-east-1"
  product_display_name = "Agent Kernel"
  is_production        = false

  # Standard queue configuration
  fifo_queue                = false
  receive_wait_time_seconds = 20  # Enable long polling

  # Access control
  producer_arns      = [aws_lambda_function.producer.arn]
  consumer_role_arns = [aws_iam_role.consumer.arn]

  tags = {
    Environment = "development"
    Team        = "platform"
  }
}
```

### Standard Queue Without DLQ

```hcl
module "simple_queue" {
  source = "./modules/sqs"

  product_alias         = "agent-kernel"
  env_alias            = "dev"
  module_name          = "processing"
  queue_name           = "simple-requests"
  region               = "us-east-1"
  product_display_name = "Agent Kernel"
  is_production        = false

  # Standard queue without DLQ
  fifo_queue = false
  create_dlq = false

  # Disable access policies for simple use case
  enable_producer_access = false
  enable_consumer_access = false

  tags = {
    Environment = "development"
    Team        = "platform"
  }
}
```

### FIFO Queue for Chat System

```hcl
module "chat_queue" {
  source = "./modules/sqs"

  product_alias         = "agent-kernel"
  env_alias            = "dev"
  module_name          = "chat"
  queue_name           = "messages"
  region               = "us-east-1"
  product_display_name = "Agent Kernel"
  is_production        = false

  # FIFO queue configuration optimized for chat
  fifo_queue                   = true
  content_based_deduplication  = false  # Use explicit MessageDeduplicationId
  deduplication_scope         = "messageGroup"  # Per thread deduplication
  fifo_throughput_limit       = "perMessageGroup"  # Higher throughput per thread

  # Access control
  producer_arns      = [aws_lambda_function.chat_producer.arn]
  consumer_role_arns = [aws_iam_role.chat_consumer.arn]

  tags = {
    Environment = "development"
    Team        = "platform"
    Application = "chat"
  }
}
```

### Production Queue with Custom KMS Encryption

```hcl
module "secure_queue" {
  source = "./modules/sqs"

  product_alias         = "agent-kernel"
  env_alias            = "prod"
  module_name          = "payments"
  queue_name           = "transactions"
  region               = "us-east-1"
  product_display_name = "Agent Kernel"
  is_production        = true

  # Enable customer-managed KMS encryption
  sqs_managed_sse_enabled           = false
  kms_master_key_id                = aws_kms_key.sqs.arn
  kms_data_key_reuse_period_seconds = 300

  # Production settings
  message_retention_seconds     = 86400  # 24 hours
  dlq_message_retention_seconds = 86400  # 24 hours
  max_receive_count            = 3       # Fail faster in production

  # Access control
  producer_arns      = [aws_lambda_function.payment_producer.arn]
  consumer_role_arns = [aws_iam_role.payment_consumer.arn]

  tags = {
    Environment = "production"
    Compliance  = "pci-dss"
    DataClass   = "sensitive"
  }
}
```

### High-Throughput FIFO Queue

```hcl
module "high_throughput_queue" {
  source = "./modules/sqs"

  product_alias         = "trading-app"
  env_alias            = "prod"
  module_name          = "orders"
  queue_name           = "executions"
  region               = "us-east-1"
  product_display_name = "Trading Application"
  is_production        = true

  # High-throughput FIFO configuration
  fifo_queue                   = true
  fifo_throughput_limit       = "perMessageGroup"  # 3000 TPS per message group
  deduplication_scope         = "messageGroup"     # Dedup per trading symbol
  content_based_deduplication = false              # Use explicit dedup IDs

  # Optimized for high-frequency trading
  visibility_timeout_seconds = 30   # Fast processing expected
  max_receive_count         = 2     # Fail fast for time-sensitive data
  
  # Access control
  producer_arns      = [
    aws_lambda_function.order_processor.arn,
    aws_ecs_task_definition.trading_engine.execution_role_arn
  ]
  consumer_role_arns = [aws_iam_role.execution_consumer.arn]

  tags = {
    Environment = "production"
    Application = "trading"
    Criticality = "high"
  }
}
```

## Configuration Reference

### Required Variables

| Name | Description | Type | Example |
|------|-------------|------|---------|
| `product_alias` | Product alias for resource naming | `string` | `"agent-kernel"` |
| `env_alias` | Environment alias | `string` | `"dev"`, `"staging"`, `"prod"` |
| `module_name` | Module name for queue identification | `string` | `"chat"`, `"processing"`, `"notifications"` |
| `queue_name` | Queue name suffix | `string` | `"messages"`, `"requests"`, `"events"` |
| `region` | AWS region | `string` | `"us-east-1"`, `"eu-west-1"` |
| `product_display_name` | Human-readable product name | `string` | `"Agent Kernel"` |
| `is_production` | Production environment flag | `bool` | `true`, `false` |

### Queue Configuration

| Name | Description | Type | Default | Notes |
|------|-------------|------|---------|-------|
| `fifo_queue` | Create FIFO (true) or standard (false) queue | `bool` | `true` | FIFO provides ordering guarantees |
| `create_dlq` | Create dead letter queue | `bool` | `true` | Optional, set to `false` to disable DLQ |
| `max_message_size` | Maximum message size in bytes | `number` | `262144` | 256KB, max is 256KB |
| `message_retention_seconds` | Message retention period | `number` | `3600` | 1 hour to 14 days |
| `visibility_timeout_seconds` | Message visibility timeout | `number` | `60` | Should exceed processing time |
| `receive_wait_time_seconds` | Long polling wait time | `number` | `0` | 0-20 seconds, enables long polling |
| `delay_seconds` | Message delivery delay | `number` | `0` | 0-900 seconds |

### Dead Letter Queue Configuration (Optional)

| Name | Description | Type | Default | Notes |
|------|-------------|------|---------|-------|
| `max_receive_count` | Max receives before DLQ | `number` | `5` | Only applies when `create_dlq = true` |
| `dlq_message_retention_seconds` | DLQ message retention | `number` | `3600` | Only applies when `create_dlq = true` |

### FIFO-Specific Configuration

| Name | Description | Type | Default | Notes |
|------|-------------|------|---------|-------|
| `content_based_deduplication` | Enable content-based deduplication | `bool` | `false` | Use explicit MessageDeduplicationId instead |
| `deduplication_scope` | Deduplication scope | `string` | `"messageGroup"` | `"queue"` or `"messageGroup"` |
| `fifo_throughput_limit` | Throughput limit type | `string` | `"perMessageGroup"` | `"perQueue"` (300 TPS) or `"perMessageGroup"` (3000 TPS) |

### Encryption Configuration

| Name | Description | Type | Default | Notes |
|------|-------------|------|---------|-------|
| `sqs_managed_sse_enabled` | Use SQS-managed encryption | `bool` | `true` | Recommended for most use cases |
| `kms_master_key_id` | Customer-managed KMS key ARN | `string` | `null` | Required when `sqs_managed_sse_enabled = false` |
| `kms_data_key_reuse_period_seconds` | KMS data key reuse period | `number` | `null` | 60-86400 seconds |

### Access Control Configuration

| Name | Description | Type | Default | Notes |
|------|-------------|------|---------|-------|
| `enable_producer_access` | Enable producer IAM policy | `bool` | `true` | Creates SendMessage permissions |
| `producer_arns` | Producer ARNs (Lambda, ECS, EC2) | `list(string)` | `[]` | Required if `enable_producer_access = true` |
| `enable_consumer_access` | Enable consumer IAM policy | `bool` | `true` | Creates ReceiveMessage permissions |
| `consumer_role_arns` | Consumer role ARNs | `list(string)` | `[]` | Required if `enable_consumer_access = true` |

### Tagging

| Name | Description | Type | Default |
|------|-------------|------|---------|
| `tags` | Additional resource tags | `map(string)` | `{}` |

## Outputs

| Name | Description | Type | Conditional |
|------|-------------|------|-------------|
| `queue_url` | URL of the main SQS queue | `string` | Always |
| `queue_arn` | ARN of the main SQS queue | `string` | Always |
| `queue_name` | Name of the main SQS queue | `string` | Always |
| `queue_id` | ID of the main SQS queue | `string` | Always |
| `dlq_url` | URL of the dead letter queue | `string` | When `create_dlq = true` |
| `dlq_arn` | ARN of the dead letter queue | `string` | When `create_dlq = true` |
| `dlq_name` | Name of the dead letter queue | `string` | When `create_dlq = true` |
| `dlq_id` | ID of the dead letter queue | `string` | When `create_dlq = true` |

### Output Usage Examples

```hcl
# Reference queue in Lambda event source mapping
resource "aws_lambda_event_source_mapping" "sqs_trigger" {
  event_source_arn = module.processing_queue.queue_arn
  function_name    = aws_lambda_function.processor.function_name
  batch_size       = 10
}

# Use queue URL in application configuration
resource "aws_ssm_parameter" "queue_url" {
  name  = "/app/queue/processing/url"
  type  = "String"
  value = module.processing_queue.queue_url
}

# Monitor DLQ for failed messages
resource "aws_cloudwatch_metric_alarm" "dlq_messages" {
  count = module.processing_queue.dlq_arn != null ? 1 : 0
  
  alarm_name          = "sqs-dlq-messages"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "2"
  metric_name         = "ApproximateNumberOfMessages"
  namespace           = "AWS/SQS"
  period              = "300"
  statistic           = "Average"
  threshold           = "0"
  alarm_description   = "Messages in DLQ"

  dimensions = {
    QueueName = module.processing_queue.dlq_name
  }
}
```

## Choosing Between FIFO and Standard Queues

### Use FIFO Queues When:
- **Message ordering is critical** (e.g., chat messages, financial transactions)
- **Exactly-once processing** is required
- **Deduplication** is needed to prevent duplicate processing
- You can work within FIFO throughput limits (300 TPS per queue, 3000 TPS per message group)

### Use Standard Queues When:
- **High throughput** is more important than ordering (nearly unlimited TPS)
- **Message ordering is not critical** (e.g., log processing, batch jobs)
- **At-least-once delivery** is acceptable
- You need **long polling** for efficient message retrieval

## Queue Naming Convention

The module automatically generates queue names using a standardized pattern to ensure consistency across environments and prevent naming conflicts.

### Naming Pattern

**FIFO Queues:**
```
{product_alias}-{env_alias}-{module_name}-{queue_name}.fifo
{product_alias}-{env_alias}-{module_name}-{queue_name}-dlq.fifo
```

**Standard Queues:**
```
{product_alias}-{env_alias}-{module_name}-{queue_name}
{product_alias}-{env_alias}-{module_name}-{queue_name}-dlq
```

### Examples

| Configuration | Main Queue | DLQ |
|---------------|------------|-----|
| `product_alias = "agent-kernel"`<br>`env_alias = "dev"`<br>`module_name = "chat"`<br>`queue_name = "messages"`<br>`fifo_queue = true` | `agent-kernel-dev-chat-messages.fifo` | `agent-kernel-dev-chat-messages-dlq.fifo` |
| `product_alias = "trading-app"`<br>`env_alias = "prod"`<br>`module_name = "orders"`<br>`queue_name = "executions"`<br>`fifo_queue = false` | `trading-app-prod-orders-executions` | `trading-app-prod-orders-executions-dlq` |

### Naming Best Practices

- **module_name**: Use functional area names (`chat`, `orders`, `notifications`, `processing`)
- **queue_name**: Use descriptive suffixes (`messages`, `events`, `requests`, `responses`)
- **Avoid**: Generic names like `queue`, `data`, `items`
- **Length**: Keep total name under 80 characters (AWS limit is 80 chars)

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

## Dead Letter Queue (DLQ) - Optional

The module can optionally create a DLQ that receives messages after they fail to be processed `max_receive_count` times (default: 5). DLQ creation is controlled by the `create_dlq` variable and is **enabled by default**.

**With DLQ (default behavior):**
```hcl
module "queue_with_dlq" {
  source = "./modules/sqs"
  
  # ... other configuration ...
  
  create_dlq        = true  # Default value - can be omitted
  max_receive_count = 3     # Fail after 3 attempts
}
```

**Without DLQ (simple queue):**
```hcl
module "simple_queue" {
  source = "./modules/sqs"
  
  # ... other configuration ...
  
  create_dlq = false  # Explicitly disable DLQ
}
```

### DLQ Characteristics

When `create_dlq = true`, the module creates a DLQ with:
- **Same queue type**: FIFO DLQ for FIFO main queue, standard DLQ for standard main queue
- **Same encryption**: Inherits encryption settings from main queue
- **Retention**: 1 hour (3,600 seconds) by default, configurable via `dlq_message_retention_seconds`
- **Automatic naming**: Appends `-dlq` to the main queue name

### When to Use DLQ

**Enable DLQ when:**
- Running in production environments
- Processing critical messages that shouldn't be lost
- Need to debug failed message processing
- Want to implement retry mechanisms with exponential backoff

**Disable DLQ when:**
- Processing non-critical messages (logs, metrics)
- Implementing custom error handling
- Working in development/testing environments
- Messages have short-lived relevance (real-time data)

## Best Practices

1. **Naming Convention**: Use descriptive suffixes that indicate the queue's purpose (e.g., 'requests', 'events', 'notifications')

2. **Visibility Timeout**: Set appropriately for your consumer processing time. Too short causes reprocessing; too long delays error detection.

3. **DLQ Strategy**: Enable DLQ for production workloads, disable for development or non-critical messages.

4. **Message Retention**: Balance between operational needs and storage costs. Default is 1 hour for both main queue and DLQ.

5. **Access Control**: Always specify producer and consumer ARNs when using IAM policies. Avoid using wildcards.

6. **Encryption**: Use customer-managed KMS keys only for sensitive data or compliance requirements.

7. **Monitoring**: Set up CloudWatch alarms for:
   - Messages in DLQ (if enabled)
   - Queue depth
   - Message age

8. **Testing**: Test DLQ behavior (if enabled) by intentionally failing message processing to ensure proper error handling.

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
