# AWS Containerized Deployment

Scalable, production-ready deployment of Agent Kernel on AWS using ECS Fargate with optional queue-based processing and auto-scaling.

## 📋 Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Deployment Modes](#deployment-modes)
- [Auto Scaling](#auto-scaling)
- [Examples](#examples)
- [Migration](#migration)

## Overview

This deployment uses AWS ECS Fargate to run containerized Agent Kernel applications with:

- ✅ **Automatic scaling** based on queue depth
- ✅ **Async processing** with SQS queues
- ✅ **Session persistence** with Redis or DynamoDB
- ✅ **Load balancing** with ALB and API Gateway
- ✅ **Modular configuration** with config objects

## Architecture

### Non-Queue Mode (Direct Execution)

```
┌─────────────┐      ┌─────┐      ┌──────────────┐
│ API Gateway │─────▶│ ALB │─────▶│ REST Service │
│   (HTTP)    │      │     │      │  (ECS Task)  │
└─────────────┘      └─────┘      │              │
                                   │ • Request    │
                                   │ • Agent      │
                                   │ • Response   │
                                   └──────────────┘
```

The REST service contains both request handling and agent execution in a single container.

### Queue Mode (Async Execution)

```
┌─────────────┐      ┌─────┐      ┌──────────────┐
│ API Gateway │─────▶│ ALB │─────▶│ REST Service │
│   (HTTP)    │      │     │      │  (ECS Task)  │
└─────────────┘      └─────┘      │              │
                                   │ • Thread 1   │
                                   │   (Request)  │
                                   │ • Thread 2   │
                                   │   (Response) │
                                   └──────┬───────┘
                                          │
                     ┌────────────────────┴────────────────────┐
                     │                                          │
                     ▼                                          ▼
              ┌─────────────┐                           ┌─────────────┐
              │ Input Queue │                           │Output Queue │
              │    (SQS)    │                           │    (SQS)    │
              └──────┬──────┘                           └──────▲──────┘
                     │                                          │
                     │          ┌──────────────┐               │
                     └─────────▶│Agent Runner  │───────────────┘
                                │  (ECS Task)  │
                                │              │
                                │ • Poll Input │
                                │ • Run Agent  │
                                │ • Send Output│
                                └──────┬───────┘
                                       │
                                       ▼
                              ┌──────────────────┐
                              │  Auto Scaling    │
                              │                  │
                              │ Scales 0-N tasks │
                              │ based on queue   │
                              │ backlog          │
                              └──────────────────┘

              ┌──────────────────┐
              │  Response Store  │
              │    (DynamoDB)    │
              │                  │
              │ Maps request IDs │
              │ to responses     │
              └──────────────────┘
```

The REST service handles HTTP requests while Agent Runner processes the actual agent logic from queues.

## Quick Start

### Basic Deployment

```hcl
module "containerized_agents" {
  source  = "yaalalabs/ak-containerized/aws"
  version = "0.6.0"

  product_alias = "my-agent"
  env_alias     = "dev"
  module_name   = "chatbot"
  region        = "us-east-1"
  
  # REST Service configuration
  rest_service = {
    package_path = "./dist"
    cpu          = 256
    memory       = 512
    environment_variables = {
      OPENAI_API_KEY = var.api_key
    }
  }
  
  # Session storage
  create_redis_cluster = true
}
```

### Scalable Queue-Based Deployment

```hcl
module "containerized_agents" {
  source  = "yaalalabs/ak-containerized/aws"
  version = "0.6.0"

  product_alias = "my-agent"
  env_alias     = "prod"
  module_name   = "assistant"
  region        = "us-east-1"
  
  # REST Service (handles HTTP requests)
  rest_service = {
    package_path  = "./dist-rest-service"
    cpu           = 512
    memory        = 1024
    desired_count = 2
    command       = ["python", "app_rest_service.py"]
    environment_variables = {
      OPENAI_API_KEY = var.api_key
    }
  }
  
  # Enable queue mode
  enable_queue_mode = true
  queue_mode_type   = "async"  # or "sync"
  
  # Queue configuration
  queue_config = {
    input_queue_visibility_timeout  = 120
    output_queue_visibility_timeout = 60
    input_queue_create_dlq          = true
    output_queue_create_dlq         = true
  }
  
  # Agent Runner (processes from queue)
  agent_runner = {
    cpu           = 1024
    memory        = 2048
    desired_count = 1
    package_path  = "../dist-agent-runner"  # Build separate image
    command       = ["python", "app_agent_runner.py"]
    environment_variables = {
      OPENAI_API_KEY = var.api_key
    }
  }
  
  # Auto scaling
  scaling_config = {
    enabled            = true
    min_count          = 1
    max_count          = 10
    backlog_target     = 5
    scale_in_cooldown  = 180
    scale_out_cooldown = 60
  }
  
  create_dynamodb_memory_table = true
}
```

## Configuration

### REST Service Object

```hcl
rest_service = {
  package_path          = null         # Path to build Docker image (required)
  cpu                   = 256          # Fargate CPU units (256, 512, 1024, etc.)
  memory                = 512          # Fargate memory in MiB
  desired_count         = 1            # Number of tasks
  container_port        = 8000         # Container port
  health_check_endpoint = "/health"    # Health check path
  image_uri             = null         # Pre-built image URI (alternative to package_path)
  command               = null         # Override Docker CMD
  environment_variables = {}           # Service-specific env vars
}
```

### Agent Runner Object

```hcl
agent_runner = {
  cpu                   = 512          # Fargate CPU units
  memory                = 1024         # Fargate memory in MiB
  desired_count         = 1            # Initial task count
  package_path          = null         # Path to build agent runner Docker image
  image_uri             = null         # Or provide pre-built image URI
  command               = null         # Override Docker CMD
  environment_variables = {}           # Service-specific env vars
}
```

**Image Resolution Priority:**
1. If `package_path` is provided → Build Docker image from path
2. Else if `image_uri` is provided → Use specified image
3. Else → Use REST service image (from `package_path`)

### Queue Config Object

```hcl
queue_config = {
  # Queue names (optional customization)
  input_queue_name  = "input-queue"    # Queue name suffix
  output_queue_name = "output-queue"   # Queue name suffix

  # Shared settings
  sqs_managed_sse_enabled   = true     # Enable SSE for queues
  max_message_size          = 262144   # 256 KB max message size
  receive_wait_time_seconds = 0        # Long polling wait time
  
  # Input queue (requests → agent runner)
  input_queue_visibility_timeout            = 60     # Should be >= processing time
  input_queue_message_retention_seconds     = 1800   # 30 minutes
  input_queue_max_receive_count             = 5      # Before DLQ
  input_queue_create_dlq                    = false  # Create dead letter queue
  input_queue_dlq_message_retention_seconds = 1800
  
  # Output queue (agent runner → REST service)
  output_queue_visibility_timeout            = 60
  output_queue_message_retention_seconds     = 1800
  output_queue_max_receive_count             = 5
  output_queue_create_dlq                    = false
  output_queue_dlq_message_retention_seconds = 1800
}
```

### Scaling Config Object

```hcl
scaling_config = {
  enabled            = false   # Enable auto scaling
  min_count          = 0       # Minimum tasks (0 to scale to zero)
  max_count          = 10      # Maximum tasks
  backlog_target     = 10      # Target messages per task
  scale_in_cooldown  = 120     # Seconds before scaling in again
  scale_out_cooldown = 30      # Seconds before scaling out again
}
```

## Deployment Modes

### Non-Queue Mode (Default)

Direct synchronous execution. The REST service contains both request handling and agent logic.

**Use when:**
- Simple, low-volume workloads
- Quick response times required
- No need for background processing

**Configuration:**
```hcl
enable_queue_mode = false  # This is the default
```

### Queue Mode - Sync

Requests use queues but client connection stays open until response is ready.

**Use when:**
- Need queue benefits (reliability, retry)
- Can tolerate slightly longer response times
- Want to keep simple client code

**Configuration:**
```hcl
enable_queue_mode = true
queue_mode_type   = "sync"
```

### Queue Mode - Async

Requests return immediately with a request ID. Client polls for results.

**Use when:**
- Long-running agent tasks
- High-volume concurrent requests
- Need maximum scalability

**Configuration:**
```hcl
enable_queue_mode = true
queue_mode_type   = "async"
```

**Client flow:**
```bash
# 1. Submit request
curl -X POST .../chat -d '{"prompt":"..."}'
# Returns: {"status":"ACCEPTED","request_id":"..."}

# 2. Poll for result
curl -X GET .../chat/{session_id}?request_id=...
# Returns: {"result":"..."}
```

## Auto Scaling

### How It Works

The agent runner automatically scales based on queue backlog:

1. **Lambda function** runs every minute calculating:
   ```
   BacklogPerTask = QueueDepth / max(RunningTasks, 1)
   ```

2. **CloudWatch metric** published:
   - Namespace: `Custom/ECS`
   - Metric: `BacklogPerTask`
   - Dimensions: `ClusterName`, `ServiceName`

3. **Target Tracking** adjusts task count to maintain target:
   - `BacklogPerTask > backlog_target` → Scale out
   - `BacklogPerTask < backlog_target` → Scale in

### Configuration Example

```hcl
scaling_config = {
  enabled            = true
  min_count          = 1    # Never scale below 1
  max_count          = 20   # Never scale above 20
  backlog_target     = 5    # Target 5 messages per task
  scale_in_cooldown  = 300  # Wait 5min before scaling in
  scale_out_cooldown = 60   # Wait 1min before scaling out
}
```

### Choosing `backlog_target`

The `backlog_target` determines how aggressively to scale:

| Target | Behavior | Use Case |
|--------|----------|----------|
| 5-10 | Aggressive scaling | Cost-sensitive, can tolerate queue buildup |
| 2-5 | Balanced | General purpose |
| 1 | Very aggressive | Low-latency, cost is less important |

**Example:**
- Queue has 100 messages
- Target is 10 messages per task
- System scales to 10 tasks
- When queue drains to 20 messages
- System scales down to 2 tasks

### Cost Optimization

**Scale to zero:**
```hcl
scaling_config = {
  enabled   = true
  min_count = 0  # Scale to zero when idle
}
```

**Gradual scale-in:**
```hcl
scaling_config = {
  scale_in_cooldown = 300  # Wait 5min before scaling in
}
```

### Monitoring

**CloudWatch Metrics:**
- `Custom/ECS/BacklogPerTask` - Custom metric
- `AWS/SQS/ApproximateNumberOfMessagesVisible` - Queue depth
- `AWS/ECS/CPUUtilization` - Task CPU usage
- `AWS/ECS/MemoryUtilization` - Task memory usage

**CloudWatch Logs:**
- `/aws/lambda/{prefix}-backlog-metric` - Scaling Lambda logs
- `/ecs/{prefix}-agent-runner` - Agent runner logs

## Examples

See [examples/aws-containerized/](../../examples/aws-containerized/) for complete examples:

- **openai-dynamodb-scalable** - Production-ready OpenAI agent with auto-scaling

## Migration

Migrating from version 0.4.0 or earlier? See:

- [MIGRATION_GUIDE.md](./MIGRATION_GUIDE.md) - Step-by-step migration guide
- [REFACTORING_SUMMARY.md](./REFACTORING_SUMMARY.md) - Detailed changes overview
- [CHANGELOG.md](./CHANGELOG.md) - Version history

## Module Documentation

For detailed module documentation, see:

- [modules/README.md](./modules/README.md) - Module architecture and usage
- [modules/queues/](./modules/queues/) - Queue module
- [modules/rest-service/](./modules/rest-service/) - REST service module
- [modules/agent-runner/](./modules/agent-runner/) - Agent runner module

## Outputs

The module provides these outputs:

```hcl
output "agent_invoke_url"           # API Gateway endpoint URL
output "alb_dns_name"               # ALB DNS name
output "cluster_arn"                # ECS cluster ARN
output "rest_service_name"          # ECS REST service name
output "agent_runner_service_name"  # ECS agent runner service name (queue mode)
output "input_queue_url"            # Input queue URL (queue mode)
output "output_queue_url"           # Output queue URL (queue mode)
output "vpc_id"                     # VPC ID
output "private_subnet_ids"         # Private subnet IDs
```

## Requirements

- **Terraform**: >= 1.9.5
- **AWS Provider**: >= 6.11.0
- **Docker Provider**: 3.6.2

## Support

For issues, questions, or contributions:

- 📖 [Documentation](./modules/README.md)
- 🐛 [Report Issues](https://github.com/your-org/agent-kernel/issues)
- 💬 [Discussions](https://github.com/your-org/agent-kernel/discussions)
