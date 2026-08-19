# AWS Containerized Deployment

Scalable, production-ready deployment of Agent Kernel on AWS using ECS Fargate with optional queue-based processing and auto-scaling.

## 📋 Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Providers](#providers)
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
  source    = "yaalalabs/ak-containerized/aws"
  version   = "0.8.1"
  providers = { aws = aws, docker = docker }

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
  # Or provision a Valkey (ElastiCache) cluster instead — set session.type: valkey in config.yaml.
  # create_valkey_cluster = true
}
```

### Scalable Queue-Based Deployment

```hcl
module "containerized_agents" {
  source    = "yaalalabs/ak-containerized/aws"
  version   = "0.8.1"
  providers = { aws = aws, docker = docker }

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
  queue_mode     = true
  execution_mode = "rest_async"  # rest_sync | rest_async | async | stream

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

  # Conversation threads: provisions a DynamoDB thread table and injects its name as
  # AK_THREAD__DYNAMODB__TABLE_NAME into the rest-service and agent-runner tasks.
  # Declare `thread: {type: dynamodb}` in config.yaml to actually enable threads —
  # this flag alone leaves them in-memory. Makes user_id required on every chat request.
  create_dynamodb_thread_table = true
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
  health_check_grace_period_seconds = 120 # ECS ignores ALB unhealthy signals for this long after task start
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
  batch_size                = 10       # Max messages fetched per SQS receive call (1-10), ECS consumers only

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

`queue_config.batch_size` is injected into both the REST service and Agent Runner ECS tasks as `AK_EXECUTION__QUEUES__BATCH_SIZE`. It only applies to ECS containerized deployments (never serverless/Lambda, which controls batch size via the Event Source Mapping) and is intentionally controlled only via Terraform — it must never be set in `config.yaml`.

### API Gateway Access Logging

| Variable | Description | Type | Default | Required |
|---|---|---|---|---|
| `enable_api_gateway_logs` | Create the CloudWatch log group and enable access logging on the HTTP API stage (or the WebSocket API stage, in WebSocket modes) | `bool` | `false` | no |

```hcl
enable_api_gateway_logs = true
```

- Off by default, matching the AWS serverless deployment. When `false`:
  - **REST/queue modes:** no `/aws/apigateway/{product_alias}-{env_alias}-http-api` log group is created and the HTTP API stage carries no `access_log_settings`; the `api_gateway_cloudwatch_log_group_arn` / `api_gateway_cloudwatch_log_group_name` outputs return `null`.
  - **WebSocket modes:** no `/aws/apigateway/{product_alias}-{env_alias}-ws-api` log group is created, the WebSocket API stage carries no `access_log_settings`, and the account-level CloudWatch role (`aws_iam_role.apigw_cloudwatch` / `aws_api_gateway_account.this`) is not created; the `websocket_api_cloudwatch_log_group_arn` / `websocket_api_cloudwatch_log_group_name` outputs return `null`.
- When `true`, the relevant log group is created with 90-day retention (tagged with `var.tags`). REST/queue modes log request ID, source IP, request time, protocol, HTTP method, route key, status, response length, and integration error message; WebSocket modes log the same fields plus `connectionId` in place of HTTP method.
- Unlike the serverless REST API, the HTTP API (`aws_apigatewayv2_*` with `protocol_type = "HTTP"`) does **not** require the account-level `aws_api_gateway_account` CloudWatch role for access logging, so enabling it there does not contend with other deployments in the same account/region. The WebSocket API (`protocol_type = "WEBSOCKET"`) **does** require that account-level role — it is created only when `enable_api_gateway_logs = true` in a WebSocket mode, and it is a region-wide singleton shared with any other API Gateway in the account that also enables access logging.
- **Upgrade note:** deployments created before this toggle existed always had logging on. Applying with the new default (`false`) removes the stage's access log settings and destroys the log group (and, in WebSocket modes, the account-level CloudWatch role resources). Set `enable_api_gateway_logs = true` to keep the existing behaviour.
- **Upgrade note (keeping logging on):** the log groups (and, in WebSocket modes, the IAM role/policy attachment/account resources) are now gated by `count`, so their state addresses gained a `[0]` index. Before the first apply with `enable_api_gateway_logs = true`, move each affected resource, e.g.:

  ```bash
  terraform state mv \
    'module.<module_name>.aws_cloudwatch_log_group.http_api' \
    'module.<module_name>.aws_cloudwatch_log_group.http_api[0]'

  # WebSocket modes only:
  terraform state mv \
    'module.<module_name>.aws_cloudwatch_log_group.ws_api' \
    'module.<module_name>.aws_cloudwatch_log_group.ws_api[0]'
  terraform state mv \
    'module.<module_name>.aws_iam_role.apigw_cloudwatch' \
    'module.<module_name>.aws_iam_role.apigw_cloudwatch[0]'
  terraform state mv \
    'module.<module_name>.aws_iam_role_policy_attachment.apigw_cloudwatch' \
    'module.<module_name>.aws_iam_role_policy_attachment.apigw_cloudwatch[0]'
  terraform state mv \
    'module.<module_name>.aws_api_gateway_account.this' \
    'module.<module_name>.aws_api_gateway_account.this[0]'
  ```

  Skipping this makes Terraform destroy and recreate these resources, discarding any retained logs.

### Scheduling (EventBridge Scheduler)

| Variable | Description | Type | Default | Required |
|---|---|---|---|---|
| `enable_scheduling` | Create the EventBridge Scheduler schedule group and the execution role Scheduler assumes to deliver triggers to the Input Queue, grant both ECS task roles `scheduler:*Schedule` + `iam:PassRole` on them, and inject their coordinates. **Requires `queue_mode = true`.** | `bool` | `false` | no |
| `create_dynamodb_schedule_table` | Create the DynamoDB schedule store table (partition `task_id`, no sort key, no GSI, TTL on `expiry_time`) and inject its generated name as `AK_SCHEDULE__STORE__DYNAMODB__TABLE_NAME` | `bool` | `false` | no |

```hcl
queue_mode                     = true
enable_scheduling              = true
create_dynamodb_schedule_table = true
```

- Off by default; every resource is `count`-gated, so leaving both `false` provisions nothing and
  injects nothing.
- **You must also declare the backends in the application's `config.yaml`** — Terraform injects the
  group/role/queue/table coordinates but never `schedule.provider.type` or `schedule.store.type`
  (the same rule as `thread.type`):

  ```yaml
  schedule:
    provider:
      type: eventbridge
    store:
      type: dynamodb
  ```

  Setting the flags without this block leaves scheduling on the default `local` provider and
  `in_memory` store, and the provisioned group and table sit unused with no error.
- `enable_scheduling` flips the **Input Queue** to `content_based_deduplication = true` (an in-place
  update on an existing queue). EventBridge Scheduler cannot set a `MessageDeduplicationId`, so
  without it two occurrences carrying an otherwise identical trigger body would collapse into one
  inside the 5-minute dedup window. Application senders are unaffected: they always send an explicit
  `MessageDeduplicationId`, which takes precedence. The Output Queue is untouched.
- Both task roles get the schedule permissions: the REST service serves the management routes
  (amend/cancel reach Scheduler), and the agent runner hosts the `create_schedule` /
  `update_schedule` / `delete_schedule` agent tools.
- See the [scheduling guide](https://kernel.yaala.ai/docs/advanced/scheduling) for the application
  side.

## Deployment Modes

### Non-Queue Mode (Default)

Direct synchronous execution. The REST service contains both request handling and agent logic.

**Use when:**

- Simple, low-volume workloads
- Quick response times required
- No need for background processing

**Configuration:**

```hcl
queue_mode = false  # This is the default
```

### Queue Mode - REST Sync (`rest_sync`)

Requests use queues but the client HTTP connection stays open until the response is ready.

**Use when:**

- Need queue benefits (reliability, retry)
- Can tolerate slightly longer response times
- Want to keep simple client code

**Configuration:**

```hcl
queue_mode     = true
execution_mode = "rest_sync"
```

### Queue Mode - REST Async (`rest_async`)

Requests return immediately with a request ID. Client polls a separate GET endpoint for results.

**Use when:**

- Long-running agent tasks
- High-volume concurrent requests
- Need maximum scalability

**Configuration:**

```hcl
queue_mode     = true
execution_mode = "rest_async"
```

**Client flow:**

```bash
# 1. Submit request
curl -X POST .../chat -d '{"session_id":"...","prompt":"..."}'
# Returns: {"status":"ACCEPTED","request_id":"...","session_id":"..."}

# 2. Poll for result (request_id required, session_id optional)
curl -X GET ".../chat?request_id=..."
# Returns the stored response body directly, e.g.: {"...": "..."}
```

### WebSocket Mode - Async (`async`) and Stream (`stream`)

Creates a **WebSocket API Gateway** that proxies frames to the ECS ingress service over a
dedicated VPC Link (V1) and an internal NLB that fronts the same internal ALB — WebSocket
private integrations require a V1, NLB-backed link, so the HTTP API's V2 link is not created
in these modes. The ingress service handles the connection lifecycle
(`$connect`/`$disconnect`) and pushes replies back to the client via `PostToConnection`.

Both `queue_mode` settings are supported:

- `queue_mode = true` — chat frames are forwarded to the input queue, and the output-queue
  consumer pushes the reply over the socket. Adds the agent-runner service and queues.
- `queue_mode = false` — the ingress service runs the agent inline and pushes the reply
  itself. No queues and no agent-runner service.

Modes:

- `async` — the full response is delivered in one WebSocket message once the agent finishes.
- `stream` — the agent's token deltas are pushed as they're generated, each as its own
  `STREAM_CHUNK` WebSocket message. With `queue_mode = false`, the ingress service streams
  the agent inline and broadcasts each chunk directly over the connection. With
  `queue_mode = true`, `ECSStreamAgentRunner` fans out each chunk as its own Output Queue
  message and `ECSOutputConsumer` broadcasts every one as a `STREAM_CHUNK`.

**What gets created (in addition to the base — and, with `queue_mode = true`, queue-mode — resources):**

- WebSocket API Gateway (`route_selection_expression = "$request.body.route"`)
- Predefined routes `$connect`, `$disconnect`, `$default`, a configurable chat route (`ws_chat_route`, default `chat`), and any `ws_routes`
- An internal NLB in front of the existing ALB, plus a dedicated API Gateway VPC Link (V1) targeting it
- A DynamoDB `websocket-connections` table (hash `user_id`, range `connection_id`, GSI `connection_id-index`, TTL `expiry_time`)
- IAM for the REST service task role: `execute-api:ManageConnections` + connections-table access

**Not used in WebSocket modes:** the DynamoDB response store and `gateway_endpoints`
(rejected by validation) — responses are pushed over the connection instead of stored.
Authentication is handled in-app on `$connect` (bearer token with a `userId` claim);
there is no API Gateway authorizer.

**Configuration:**

```hcl
queue_mode     = true          # or false to run the agent inline in the ingress service
execution_mode = "async"

# Optional route customization
ws_chat_route = "conversation"
ws_routes = [
  { route = "notifications" },
  { route = "status_updates" },
]
```

**Route selection:** the client includes a `route` field in the JSON frame body
(e.g. `{"route":"chat","prompt":"..."}`). WebSocket `$context` values
(`routeKey`, `connectionId`, `eventType`, `domainName`, `stage`) are forwarded to
the app as `x-ws-*` request headers.

> **App contract**: WebSocket modes assume the container image supports the same
> `AK_EXECUTION__MODE = async|stream` behavior as the serverless deployment, exposes
> an HTTP ingress route for forwarded frames, reads the `x-ws-*` headers, and reads
> `AK_WEBSOCKET_API__ENDPOINT_URL` for `PostToConnection`. Verify these before use.

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

| Target | Behavior           | Use Case                                   |
| ------ | ------------------ | ------------------------------------------ |
| 5-10   | Aggressive scaling | Cost-sensitive, can tolerate queue buildup |
| 2-5    | Balanced           | General purpose                            |
| 1      | Very aggressive    | Low-latency, cost is less important        |

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
- **openai-websocket** - OpenAI agent over a WebSocket API in direct (non-queue) mode: one ECS
  service authenticates `$connect`, runs the agent inline, and pushes the reply back over the
  same connection
- **openai-websocket-scalable** - OpenAI agent over a WebSocket API in queue mode: the REST/IO
  service enqueues chat frames and pushes responses, while a separately-scalable Agent Runner
  service processes them from SQS
- **openai-stream** - OpenAI agent over a WebSocket API in direct (non-queue), STREAM execution
  mode: the reply is delivered token-by-token as `STREAM_CHUNK` messages instead of one final
  `CHAT_RESPONSE`
- **openai-stream-queue-mode** - OpenAI agent over a WebSocket API in queue-based STREAM execution
  mode: the Agent Runner streams token-by-token chunks onto the Output Queue so it can scale
  independently of ingress

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

output "api_gateway_cloudwatch_log_group_arn"   # API Gateway log group ARN (null when logging disabled)
output "api_gateway_cloudwatch_log_group_name"  # API Gateway log group name (null when logging disabled)

# WebSocket mode only (`execution_mode = "async"` or `"stream"`) — null otherwise
output "websocket_api_endpoint_url"       # WebSocket API Gateway connect URL (wss://...)
output "websocket_api_id"                 # WebSocket API Gateway ID
output "websocket_api_execution_arn"      # WebSocket API Gateway execution ARN
output "websocket_api_stage_name"         # WebSocket API Gateway stage name
output "websocket_endpoint_url"           # Management API endpoint used for PostToConnection
output "websocket_connection_table_name"  # DynamoDB connections table name
output "websocket_connection_table_arn"   # DynamoDB connections table ARN

# Scheduling only (`enable_scheduling` / `create_dynamodb_schedule_table`) — null otherwise
output "schedule_group_name"           # EventBridge Scheduler schedule-group name
output "schedule_group_arn"            # EventBridge Scheduler schedule-group ARN
output "scheduler_execution_role_arn"  # Role Scheduler assumes to deliver triggers to the Input Queue
output "schedule_table_name"           # DynamoDB schedule store table name
output "schedule_table_arn"            # DynamoDB schedule store table ARN
```

## Requirements

- **Terraform**: >= 1.9.5
- **AWS Provider**: >= 6.11.0
- **Docker Provider**: 3.6.2

## Providers

This module is provider-agnostic: it declares `aws` and `docker` in `required_providers` but does **not** configure them internally. Configure both providers in your root module and pass them explicitly via the `providers` argument. This is what lets you use `count`, `for_each`, or `depends_on` on the module block, and lets a minimal/standalone config destroy the resources it created.

```hcl
provider "aws" {
  region = var.region
}

# Docker authenticates against ECR to push the images this module builds
data "aws_caller_identity" "current" {}
data "aws_ecr_authorization_token" "token" {}

provider "docker" {
  registry_auth {
    address  = format("%v.dkr.ecr.%v.amazonaws.com", data.aws_caller_identity.current.account_id, var.region)
    username = data.aws_ecr_authorization_token.token.user_name
    password = data.aws_ecr_authorization_token.token.password
  }
}

module "containerized_agents" {
  source    = "yaalalabs/ak-containerized/aws"
  version   = "0.8.1"
  providers = { aws = aws, docker = docker }

  # ... other inputs
}
```

## Support

For issues, questions, or contributions:

- 📖 [Documentation](./modules/README.md)
- 🐛 [Report Issues](https://github.com/your-org/agent-kernel/issues)
- 💬 [Discussions](https://github.com/your-org/agent-kernel/discussions)
