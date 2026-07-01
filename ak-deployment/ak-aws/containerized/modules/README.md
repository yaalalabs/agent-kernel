# Containerized Deployment Modules

This directory contains reusable Terraform modules for the containerized Agent Kernel deployment, following the same pattern as the serverless deployment.

## Architecture Overview

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
                                └──────────────┘

              ┌──────────────────┐
              │  Response Store  │
              │    (DynamoDB)    │
              │                  │
              │ Maps request IDs │
              │ to responses     │
              └──────────────────┘
```

## Modules

### 1. `queues/`

**Purpose**: Manages SQS queues for queue-based execution mode

**Resources Created**:
- Input Queue (FIFO SQS)
- Output Queue (FIFO SQS)
- Dead Letter Queues (optional)

**Input Variables**:
```hcl
queue_config = {
  # Shared settings
  sqs_managed_sse_enabled   = true
  max_message_size          = 262144
  receive_wait_time_seconds = 0
  
  # Input queue
  input_queue_visibility_timeout            = 60
  input_queue_message_retention_seconds     = 1800
  input_queue_max_receive_count             = 5
  input_queue_create_dlq                    = false
  input_queue_dlq_message_retention_seconds = 1800
  
  # Output queue
  output_queue_visibility_timeout            = 60
  output_queue_message_retention_seconds     = 1800
  output_queue_max_receive_count             = 5
  output_queue_create_dlq                    = false
  output_queue_dlq_message_retention_seconds = 1800
}
```

**Outputs**:
- `input_queue_arn`
- `input_queue_url`
- `output_queue_arn`
- `output_queue_url`

### 2. `rest-service/`

**Purpose**: Manages the main ECS service that handles HTTP requests

**Resources Created**:
- ECS Task Definition and Service
- Application Load Balancer (ALB)
- Target Group and Listener
- Security Groups (ALB and ECS)
- Service Discovery Namespace
- IAM Policy for DynamoDB memory access

**Input Variables**:
```hcl
rest_service = {
  cpu                   = 256
  memory                = 512
  desired_count         = 1
  container_port        = 8000
  health_check_endpoint = "/health"
  image_uri             = "..."
  command               = ["python", "app.py"]
  environment_variables = {}
}
```

**Outputs**:
- `service_arn`
- `service_name`
- `task_role_name`
- `task_role_arn`
- `alb_arn`
- `alb_dns_name`
- `alb_listener_arn`
- `target_group_arn`
- `security_group_id`
- `alb_security_group_id`

**Environment Variables Injected**:
- `AK_SESSION__REDIS__URL` (if Redis enabled)
- `AK_SESSION__DYNAMODB__TABLE_NAME` (if DynamoDB memory table enabled)
- `AK_EXECUTION__QUEUES__INPUT__URL` (if queue mode enabled)
- `AK_EXECUTION__QUEUES__OUTPUT__URL` (if queue mode enabled)
- `AK_EXECUTION__RESPONSE_STORE__DYNAMODB__TABLE_NAME` (if queue mode enabled)

### 3. `agent-runner/`

**Purpose**: Manages the Agent Runner ECS service that processes messages from the input queue

**Resources Created**:
- ECS Task Definition and Service
- IAM Execution Role
- IAM Task Role
- IAM Policies (Logs, SQS, DynamoDB)
- Security Group
- CloudWatch Log Group

**Optional Auto Scaling Resources** (when `scaling_config.enabled = true`):
- Lambda Function (BacklogPerTask metric calculator)
- IAM Role and Policy for Lambda
- CloudWatch Log Group for Lambda
- EventBridge Rule (1-minute schedule)
- EventBridge Target
- Lambda Permission
- Application Auto Scaling Target
- Application Auto Scaling Policy (Target Tracking)

**Input Variables**:
```hcl
agent_runner = {
  cpu                   = 512
  memory                = 1024
  desired_count         = 1
  image_uri             = null  # Defaults to rest_service image
  command               = null
  environment_variables = {}
}

scaling_config = {
  enabled            = false
  min_count          = 0
  max_count          = 10
  backlog_target     = 10
  scale_in_cooldown  = 120
  scale_out_cooldown = 30
}
```

**Outputs**:
- `service_name`
- `service_arn`
- `task_role_arn`
- `execution_role_arn`
- `security_group_id`

**Environment Variables Injected**:
- `AK_EXECUTION__QUEUES__INPUT__URL`
- `AK_EXECUTION__QUEUES__OUTPUT__URL`
- `AK_EXECUTION__QUEUES__INPUT__MAX_RECEIVE_COUNT`
- `AK_SESSION__REDIS__URL` (if Redis enabled)
- `AK_SESSION__DYNAMODB__TABLE_NAME` (if DynamoDB memory table enabled)

**Auto Scaling Behavior**:
When `scaling_config.enabled = true`:

1. **Lambda Function** runs every minute to calculate:
   ```
   BacklogPerTask = ApproximateNumberOfMessages / max(runningCount, 1)
   ```

2. **Custom CloudWatch Metric** published:
   - Namespace: `Custom/ECS`
   - Metric: `BacklogPerTask`
   - Dimensions: `ClusterName`, `ServiceName`

3. **Target Tracking Scaling** adjusts task count to maintain `backlog_target`:
   - If `BacklogPerTask > backlog_target`: Scale out
   - If `BacklogPerTask < backlog_target`: Scale in
   - Cooldown periods prevent rapid scaling

## Usage Examples

### Basic (Non-Queue Mode)

```hcl
module "containerized_agents" {
  source = "yaalalabs/ak-containerized/aws"

  product_alias = "my-agent"
  env_alias     = "dev"
  module_name   = "chatbot"
  region        = "us-east-1"
  
  package_path = "./dist"
  
  rest_service = {
    cpu    = 256
    memory = 512
    environment_variables = {
      OPENAI_API_KEY = var.api_key
    }
  }
  
  create_redis_cluster = true
}
```

### With Queue Mode and Auto Scaling

```hcl
module "containerized_agents" {
  source = "yaalalabs/ak-containerized/aws"

  product_alias = "my-agent"
  env_alias     = "prod"
  module_name   = "assistant"
  region        = "us-east-1"
  
  package_path = "./dist-rest-service"
  
  # REST Service handles HTTP requests
  rest_service = {
    cpu           = 512
    memory        = 1024
    desired_count = 2
    command       = ["python", "app_rest_service.py"]
    environment_variables = {
      OPENAI_API_KEY = var.api_key
    }
  }
  
  # Queue mode for async processing
  enable_queue_mode = true
  queue_mode_type   = "async"
  
  queue_config = {
    input_queue_visibility_timeout  = 120
    output_queue_visibility_timeout = 60
    input_queue_create_dlq          = true
    output_queue_create_dlq         = true
  }
  
  # Agent Runner processes queue messages
  agent_runner = {
    cpu           = 1024
    memory        = 2048
    desired_count = 1
    image_uri     = "123456789.dkr.ecr.us-east-1.amazonaws.com/agent-runner:latest"
    command       = ["python", "app_agent_runner.py"]
    environment_variables = {
      OPENAI_API_KEY = var.api_key
    }
  }
  
  # Auto scaling based on queue depth
  scaling_config = {
    enabled            = true
    min_count          = 1
    max_count          = 10
    backlog_target     = 5  # Scale when >5 messages per task
    scale_in_cooldown  = 180
    scale_out_cooldown = 60
  }
  
  create_dynamodb_memory_table = true
}
```

## Design Principles

1. **Config Objects Over Flat Variables**: Group related settings into logical objects
2. **Sensible Defaults**: Provide reasonable defaults for all optional parameters
3. **Environment Variable Injection**: Automatically inject required environment variables
4. **Conditional Resources**: Only create resources when needed (e.g., scaling, DLQ)
5. **Module Independence**: Each module is self-contained and reusable
6. **Consistent Pattern**: Follows the same structure as serverless deployment

## Benefits

✅ **Clarity**: Config objects make it clear what settings belong together  
✅ **Consistency**: Same pattern as serverless deployment  
✅ **Maintainability**: Modules can be updated independently  
✅ **Flexibility**: Easy to enable/disable features (scaling, DLQ, etc.)  
✅ **Reusability**: Modules can be used in other projects  
✅ **Type Safety**: Terraform validates object structure  

## Comparison with Serverless

| Feature | Serverless | Containerized |
|---------|-----------|---------------|
| **Request Handler** | Lambda Function | ECS Task (REST Service) |
| **Agent Runner** | Lambda Function | ECS Task |
| **Compute** | AWS Lambda | AWS Fargate |
| **Scaling** | Lambda auto-scales | Custom ECS auto-scaling |
| **Config Pattern** | `request_handler` object | `rest_service` object |
| **Queue Module** | ✅ | ✅ |
| **Scaling Config** | Built-in | `scaling_config` object |
| **Load Balancer** | API Gateway direct | ALB + API Gateway |

## Migration from Old Structure

See [REFACTORING_SUMMARY.md](../REFACTORING_SUMMARY.md) for detailed migration guide.
