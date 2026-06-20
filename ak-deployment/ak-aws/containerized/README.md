# Agent Kernel - AWS Containerized Module

A comprehensive Terraform module for deploying containerized applications on AWS using ECS Fargate, with Application Load Balancer, API Gateway, and optional Redis or DynamoDB integration.

## 📋 Overview

This module provides a complete containerized deployment solution on AWS:

- 🐳 **ECS Fargate**: Serverless container orchestration with auto-scaling
- 🔄 **Application Load Balancer**: Intelligent traffic distribution and health checks
- 🌐 **API Gateway HTTP API**: RESTful API endpoints with custom routing
- 🔒 **VPC Networking**: Private subnets, NAT Gateway, and security groups
- 💾 **State Management**: Optional ElastiCache Redis or DynamoDB for session/state persistence
- 📊 **CloudWatch Monitoring**: Container logs and application metrics
- 🏗️ **Automated Build**: Docker image building and ECR management

Perfect for microservices, web applications, APIs requiring persistent connections, stateful services, and applications needing more resources than Lambda provides.

## 📋 Requirements

| Name | Version |
|------|---------|
| Terraform | >= 1.9.5 |
| AWS Provider | >= 6.11.0 |
| Docker Provider | >= 3.6.2 |

## 🚀 Usage

### Basic Containerized API

```hcl
module "container_app" {
  source = "yaalalabs/ak-containerized/aws"

  region               = "us-west-2"
  product_alias        = "myapp"
  env_alias            = "prod"
  product_display_name = "My Containerized App"
  
  module_name  = "api"
  package_path = "${path.module}/src"  # Directory with Dockerfile
  
  # ECS Configuration
  ecs_cpu            = 512
  ecs_memory         = 1024
  ecs_desired_count  = 2
  ecs_container_port = 8000
  
  # Health check
  ecs_health_check_endpoint = "/health"
  
  # Environment variables
  environment_variables = {
    ENVIRONMENT = "production"
    LOG_LEVEL   = "info"
    PORT        = "8000"
  }
  
  # API Gateway
  api_version    = "v1"
  api_base_path  = "api"
  agent_endpoint = "chat"
  gateway_endpoints = [
      {
         path           = "app",
         method         = "GET",
         overwrite_path = "/custom/task"
      },
      {
         path           = "data",
         method         = "POST",
         overwrite_path = "/app/library/data"
      }
   ] 
  
  tags = {
    Environment = "production"
    Service     = "api"
  }
}

output "api_url" {
  value = module.container_app.agent_invoke_url
}

output "alb_dns" {
  value = module.container_app.alb_dns_name
}
```

### With Existing VPC

```hcl
# Use existing VPC
module "container_app" {
  source = "yaalalabs/ak-containerized/aws"

  region               = "us-west-2"
  product_alias        = "myapp"
  env_alias            = "prod"
  product_display_name = "API Service"
  
  module_name  = "api"
  package_path = "${path.module}/docker"
  
  # Use existing VPC
  vpc_id             = "vpc-0abc123def456789"
  private_subnet_ids = ["subnet-111", "subnet-222"]
  
  ecs_cpu           = 1024
  ecs_memory        = 2048
  ecs_desired_count = 3
  
  environment_variables = {
    DB_HOST = "database.example.com"
    CACHE   = "enabled"
  }
  
  api_version    = "v2"
  agent_endpoint = "process"
}
```

### With Redis and Custom VPC

```hcl
module "container_app_redis" {
  source = "yaalalabs/ak-containerized/aws"

  region               = "us-west-2"
  product_alias        = "myapp"
  env_alias            = "prod"
  product_display_name = "Stateful API"
  
  module_name  = "stateful-api"
  package_path = "${path.module}/app"
  
  # Create new VPC with custom CIDR
  vpc_cidr             = "10.1.0.0/16"
  public_subnet_cidrs  = ["10.1.1.0/24", "10.1.2.0/24"]
  private_subnet_cidrs = ["10.1.10.0/23", "10.1.12.0/23"]
  
  # Enable Redis
  create_redis_cluster = true
  
  # ECS Configuration
  ecs_cpu            = 2048
  ecs_memory         = 4096
  ecs_desired_count  = 4
  ecs_container_port = 3000
  
  environment_variables = {
    NODE_ENV    = "production"
    WORKERS     = "4"
    # Redis URL automatically injected as AK_REDIS_URL
  }
  
  api_version    = "v1"
  agent_endpoint = "session"
}
```

### With DynamoDB for Session Storage

```hcl
module "container_app_dynamodb" {
  source = "yaalalabs/ak-containerized/aws"

  region               = "us-west-2"
  product_alias        = "myapp"
  env_alias            = "prod"
  product_display_name = "Serverless State API"
  
  module_name  = "serverless-api"
  package_path = "${path.module}/app"
  
  # Create new VPC
  vpc_cidr             = "10.2.0.0/16"
  public_subnet_cidrs  = ["10.2.1.0/24", "10.2.2.0/24"]
  private_subnet_cidrs = ["10.2.10.0/23", "10.2.12.0/23"]
  
  # Enable DynamoDB for session storage
  create_dynamodb_memory_table = true
  
  # ECS Configuration
  ecs_cpu            = 1024
  ecs_memory         = 2048
  ecs_desired_count  = 2
  ecs_container_port = 8000
  
  environment_variables = {
    NODE_ENV = "production"
    # DynamoDB table name automatically injected as AK_SESSION__DYNAMODB__TABLE_NAME
  }
  
  api_version    = "v1"
  agent_endpoint = "chat"
}
```

### High-Availability Production Setup

```hcl
module "production_app" {
  source = "yaalalabs/ak-containerized/aws"

  region               = "us-west-2"
  product_alias        = "enterprise"
  env_alias            = "prod"
  product_display_name = "Enterprise Application"
  
  module_name  = "core-api"
  package_path = "${path.module}/docker"
  
  # High-performance VPC
  vpc_cidr = "10.0.0.0/16"
  
  # Redis for low-latency session management (or use DynamoDB with create_dynamodb_memory_table = true)
  create_redis_cluster = true
  
  # High-performance ECS
  ecs_cpu           = 4096  # 4 vCPU
  ecs_memory        = 8192  # 8 GB
  ecs_desired_count = 6     # High availability
  
  ecs_container_port    = 8080
  ecs_health_check_endpoint = "/api/health"
  
  environment_variables = {
    ENVIRONMENT           = "production"
    LOG_LEVEL            = "warn"
    MAX_CONNECTIONS      = "1000"
    ENABLE_METRICS       = "true"
    GRACEFUL_SHUTDOWN_MS = "30000"
  }
  
  api_version    = "v1"
  agent_endpoint = "enterprise"
  
  tags = {
    Environment  = "production"
    Compliance   = "SOC2"
    CostCenter   = "Engineering"
    Criticality  = "high"
  }
}

# CloudWatch alarms for production
resource "aws_cloudwatch_metric_alarm" "high_cpu" {
  alarm_name          = "enterprise-prod-high-cpu"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "CPUUtilization"
  namespace           = "AWS/ECS"
  period              = 300
  statistic           = "Average"
  threshold           = 80
  
  dimensions = {
    ClusterName = module.production_app.cluster_arn
  }
}
```

### Scalable Queue Mode with SQS

For high-throughput workloads with asynchronous processing:

```hcl
module "agent_runner_image" {
  source = "yaalalabs/ak-common/aws//modules/ecr"
  
  env_alias     = var.env_alias
  module_name   = "${var.module_name}-runner"
  product_alias = var.product_alias
  source_path   = "${path.module}/dist-agent-runner"
}

module "scalable_queue_app" {
  source = "yaalalabs/ak-containerized/aws"

  region               = "us-west-2"
  product_alias        = "myapp"
  env_alias            = "prod"
  product_display_name = "Scalable Agent Service"
  
  module_name  = "scalable"
  package_path = "${path.module}/dist-rest-service"
  
  vpc_id             = var.vpc_id
  private_subnet_ids = var.private_subnet_ids
  
  # ECS Configuration for REST Service
  ecs_cpu            = 1024
  ecs_memory         = 2048
  ecs_desired_count  = 2
  ecs_container_port = 8000
  
  # Override container command (ECR module injects Lambda-style CMD)
  container_entrypoint_override = ["python", "app_rest_service.py"]
  
  # Session storage
  create_dynamodb_memory_table = true
  
  # Enable Queue Mode
  enable_queue_mode = true
  queue_mode_type   = "sync"  # or "async" for polling mode
  
  # Enable Autoscaling (optional)
  enable_agent_runner_autoscaling = true
  agent_runner_min_count          = 1
  agent_runner_max_count          = 10
  agent_runner_backlog_target     = 10
  
  # Agent Runner Configuration
  agent_runner_image_uri     = module.agent_runner_image.docker_image_uri
  agent_runner_command       = ["python", "app_agent_runner.py"]
  agent_runner_cpu           = 1024
  agent_runner_memory        = 2048
  agent_runner_desired_count = 2
  
  # SQS Configuration
  sqs_input_visibility_timeout  = 120  # Should exceed agent processing time
  sqs_output_visibility_timeout = 60
  
  environment_variables = {
    OPENAI_API_KEY = var.openai_api_key
  }
  
  api_version    = "v1"
  agent_endpoint = "chat"
}
```

**Queue Mode Architecture:**
- **REST Service** (Thread 1): Accepts HTTP requests, enqueues to Input Queue
- **REST Service** (Thread 2): Polls Output Queue, writes to DynamoDB Response Store
- **Agent Runner**: Polls Input Queue, executes agents, sends to Output Queue
- **REST_SYNC**: Client blocks until response ready in DynamoDB
- **REST_ASYNC**: Client receives `request_id`, polls GET endpoint for result

**Use Cases:**
- Long-running agent workflows (>30s)
- Workloads requiring independent scaling of API and processing
- High-throughput scenarios with bursty traffic
- Decoupling request handling from agent execution

See [examples/aws-containerized/openai-dynamodb-scalable](../../../examples/aws-containerized/openai-dynamodb-scalable/) for complete implementation.

### Agent Runner Autoscaling

When `enable_agent_runner_autoscaling = true`, the Agent Runner automatically scales based on queue backlog.

#### How It Works

A Lambda function runs every **1 minute** and calculates:

```
BacklogPerTask = ApproximateNumberOfMessages / max(RunningTasks, 1)
```

AWS Target Tracking monitors this metric and scales using:

```
New Capacity = Current Capacity × (Current Metric / Target)
```

- **Scale-out**: Aggressive and fast (~3-4 minutes)
- **Scale-in**: Conservative and gradual (~15-30 minutes, multiple cycles)

#### Configuration

```hcl
enable_agent_runner_autoscaling = true
agent_runner_min_count          = 1    # Minimum tasks (0 = scale to zero)
agent_runner_max_count          = 10   # Maximum tasks
agent_runner_backlog_target     = 10   # Target messages per task
agent_runner_scale_in_cooldown  = 120  # Seconds between scale-in
agent_runner_scale_out_cooldown = 30   # Seconds between scale-out
```

**Choosing Target Value:**
- **Lower target** (e.g., 5): Scales out sooner, more tasks, faster processing, higher cost
- **Higher target** (e.g., 20): Scales out later, fewer tasks, slower processing, lower cost
- Start with default (10), monitor queue depth and task count, then tune

#### Scaling Examples

**Scale-Out:**
```
Queue=100, Tasks=1, BacklogPerTask=100, Target=10
→ Scales to ~10 tasks quickly (2-3 minutes)
```

**Scale-In (gradual over multiple cycles):**
```
Queue=20, Tasks=10, BacklogPerTask=2, Target=10

Cycle 1: Remove 3 tasks → 7 tasks
Wait 2min (cooldown)
Cycle 2: Remove 2 tasks → 5 tasks
...continues until stable
```

#### Monitoring

**CloudWatch Metrics:**
- `Custom/ECS/BacklogPerTask` - Custom metric
- `RunningTaskCount` - ECS service
- `ApproximateNumberOfMessages` - SQS queue

**View Lambda Logs:**
```bash
aws logs tail /aws/lambda/<prefix>-backlog-metric --follow
```

**View Scaling Activity:**
```bash
aws application-autoscaling describe-scaling-activities \
  --service-namespace ecs \
  --resource-id service/<cluster>/<service>
```

#### Troubleshooting

- **Scaling too aggressively**: Increase `backlog_target` or cooldown periods
- **Not scaling fast enough**: Decrease `backlog_target`, verify Lambda is running
- **Stuck at min/max**: Check capacity limits, verify messages are being processed
- **Scale to zero not working**: Set `min_count = 0`, wait 30+ minutes for gradual scale-in

## 📥 Inputs

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|:--------:|
| `region` | AWS region for deployment | `string` | n/a | yes |
| `product_alias` | Short identifier for the product | `string` | n/a | yes |
| `env_alias` | Environment identifier (dev, staging, prod) | `string` | n/a | yes |
| `product_display_name` | Human-readable product name | `string` | `"An Agent Kernel deployment"` | no |
| `module_name` | Module name for resource identification | `string` | n/a | yes |
| `package_path` | Path to Docker source directory (with Dockerfile) | `string` | n/a | yes |
| `environment_variables` | Environment variables for container | `map(string)` | `{}` | no |
| `api_version` | API version for endpoint path | `string` | `"v1"` | no |
| `agent_endpoint` | API endpoint name | `string` | `"chat"` | no |
| `enable_mcp_server` | Enable MCP server and expose MCP API endpoint | `bool` | `false` | no |
| `tags` | Additional tags for resources | `map(string)` | `{}` | no |
| **API Gateway CORS** |
| `enable_cors` | Enable CORS on the HTTP API | `bool` | `true` | no |
| `cors_allow_origins` | CORS allowed origins | `list(string)` | `["*"]` | no |
| `cors_allow_methods` | CORS allowed methods | `list(string)` | `["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"]` | no |
| `cors_allow_headers` | CORS allowed headers | `list(string)` | `["*"]` | no |
| `cors_expose_headers` | CORS exposed headers | `list(string)` | `[]` | no |
| `cors_max_age` | CORS max age in seconds | `number` | `600` | no |
| `cors_allow_credentials` | Whether to allow credentials for CORS | `bool` | `false` | no |
| **API Gateway Throttling** |
| `throttling_rate_limit` | Steady-state RPS limit for default route (set `null` to disable) | `number` | `null` | no |
| `throttling_burst_limit` | Burst token bucket size for default route (set `null` to disable) | `number` | `null` | no |
| **VPC Configuration** |
| `vpc_cidr` | CIDR block for new VPC (if not using existing) | `string` | `"10.0.0.0/16"` | no |
| `public_subnet_cidrs` | Public subnet CIDRs | `list(string)` | `["10.0.1.0/24", "10.0.2.0/24"]` | no |
| `private_subnet_cidrs` | Private subnet CIDRs | `list(string)` | `["10.0.3.0/24", "10.0.4.0/24"]` | no |
| `vpc_id` | Existing VPC ID (if not creating new) | `string` | `null` | no |
| `private_subnet_ids` | Existing private subnet IDs | `list(string)` | `null` | no |
| **ECS Configuration** |
| `ecs_cpu` | Fargate CPU units (256, 512, 1024, 2048, 4096) | `number` | `256` | no |
| `ecs_memory` | Fargate memory in MiB | `number` | `512` | no |
| `ecs_desired_count` | Number of ECS tasks to run | `number` | `1` | no |
| `ecs_container_port` | Container port exposed by service | `number` | `8000` | no |
| `ecs_health_check_endpoint` | Health check path for ALB | `string` | `"/health"` | no |
| `container_type` | Container orchestration type (ecs or eks) | `string` | `"ecs"` | no |
| **State Management** |
| `create_redis_cluster` | Enable Redis ElastiCache cluster | `bool` | `false` | no |
| `create_dynamodb_memory_table` | Enable DynamoDB table for session storage | `bool` | `false` | no |
| **Queue Mode (Scalable Architecture)** |
| `enable_queue_mode` | Enable SQS queue mode with separate Agent Runner service | `bool` | `false` | no |
| `enable_agent_runner_autoscaling` | Enable SQS-based autoscaling for Agent Runner (requires `enable_queue_mode=true`) | `bool` | `false` | no |
| `queue_mode_type` | Queue mode type: `sync` (client blocks) or `async` (client polls) | `string` | `"sync"` | no |
| `agent_runner_image_uri` | Docker image URI for Agent Runner (required when `enable_queue_mode=true`) | `string` | `null` | conditional |
| `agent_runner_command` | Command override for Agent Runner container | `list(string)` | `null` | no |
| `agent_runner_cpu` | Fargate CPU units for Agent Runner | `number` | `1024` | no |
| `agent_runner_memory` | Fargate memory in MiB for Agent Runner | `number` | `2048` | no |
| `agent_runner_desired_count` | Number of Agent Runner tasks | `number` | `1` | no |
| `agent_runner_min_count` | Minimum tasks when autoscaling enabled | `number` | `0` | no |
| `agent_runner_max_count` | Maximum tasks when autoscaling enabled | `number` | `10` | no |
| `agent_runner_backlog_target` | Target messages per task for autoscaling (lower=more aggressive) | `number` | `10` | no |
| `agent_runner_scale_in_cooldown` | Seconds to wait before scaling in again | `number` | `120` | no |
| `agent_runner_scale_out_cooldown` | Seconds to wait before scaling out again | `number` | `30` | no |
| `sqs_input_visibility_timeout` | SQS Input Queue visibility timeout (seconds) | `number` | `30` | no |
| `sqs_output_visibility_timeout` | SQS Output Queue visibility timeout (seconds) | `number` | `30` | no |
| `container_entrypoint_override` | Command override for REST Service container | `list(string)` | `null` | no |

## 📤 Outputs

| Name | Description | Example |
|------|-------------|---------|
| `alb_dns_name` | DNS name of Application Load Balancer | `myapp-prod-alb-123456789.us-west-2.elb.amazonaws.com` |
| `cluster_arn` | ARN of the ECS cluster | `arn:aws:ecs:us-west-2:123456789012:cluster/myapp-prod-api` |
| `api_gateway_id` | API Gateway HTTP API ID | `abc123defg` |
| `api_gateway_stage` | API Gateway stage name | `default` |
| `agent_invoke_url` | Full HTTPS URL to invoke API | `https://abc123.execute-api.us-west-2.amazonaws.com/api/v1/chat` |
| `vpc_id` | VPC ID (created or used) | `vpc-0abc123def456789` |
| `redis_url` | Redis connection URL (if enabled) | `redis://myapp-prod-cache.abc123.cache.amazonaws.com:6379` |
| `dynamodb_memory_table_arn` | DynamoDB table ARN (if enabled) | `arn:aws:dynamodb:us-west-2:123456789012:table/myapp-prod-api-session_store` |
| `dynamodb_memory_table_name` | DynamoDB table name (if enabled) | `myapp-prod-api-session_store` |

## ✨ Features

### 🐳 ECS Fargate Configuration

**Serverless Containers**:
- No server management required
- Automatic scaling capabilities
- Pay only for resources used
- Multiple task sizes available

**CPU/Memory Combinations**:
| CPU (vCPU) | Memory Options (GB) |
|------------|-------------------|
| 0.25 | 0.5, 1, 2 |
| 0.5 | 1, 2, 3, 4 |
| 1 | 2, 3, 4, 5, 6, 7, 8 |
| 2 | 4-16 (1 GB increments) |
| 4 | 8-30 (1 GB increments) |

### 🔄 Load Balancer Features

- **Application Load Balancer**: Layer 7 HTTP/HTTPS routing
- **Health Checks**: Automatic unhealthy task replacement
- **Multiple AZs**: High availability across availability zones
- **Target Groups**: Efficient request distribution
- **CloudWatch Integration**: Detailed metrics and logging

### 🌐 API Gateway Integration

**HTTP API Gateway**:
```
https://{api-id}.execute-api.{region}.amazonaws.com/api/{version}/{endpoint}
```

**Features**:
- Low-latency API access
- Cost-effective compared to REST API
- VPC Link integration with ALB
- Custom domain support compatible

### 🔒 Network Security

**Private Subnet Deployment**:
- Containers run in private subnets
- Internet access via NAT Gateway
- No direct public exposure

**Security Groups**:
- ALB security group: Allows inbound HTTP/HTTPS
- ECS security group: Allows traffic from ALB only
- Redis security group: VPC-only access

### 💾 Redis Integration

**Optional ElastiCache**:
- Automatic provisioning when enabled
- Connection URL injected as `AK_REDIS_URL`
- Deployed in private subnets
- Secure VPC-only access

## 🏗️ Architecture

```
                        ┌─────────────────────┐
                        │   API Gateway       │
                        │   (HTTP API)        │
                        └──────────┬──────────┘
                                   │ HTTPS
                                   ▼
                        ┌─────────────────────┐
                        │    VPC Link         │
                        └──────────┬──────────┘
                                   │
┌──────────────────────────────────┼───────────────────────────────┐
│                       VPC         │                               │
│                                   ▼                               │
│                    ┌──────────────────────────┐                  │
│                    │  Application Load        │                  │
│                    │  Balancer (Public)       │                  │
│                    └────────────┬─────────────┘                  │
│                                 │                                │
│  ┌──────────────────────────────┼───────────────────────────┐  │
│  │         Private Subnets      │                           │  │
│  │                              ▼                           │  │
│  │          ┌────────────────────────────┐                  │  │
│  │          │   ECS Fargate Service      │                  │  │
│  │          │                            │                  │  │
│  │          │  ┌──────┐  ┌──────┐       │                  │  │
│  │          │  │Task 1│  │Task 2│  ...  │                  │  │
│  │          │  └───┬──┘  └───┬──┘       │                  │  │
│  │          └──────┼─────────┼──────────┘                  │  │
│  │                 │         │                              │  │
│  │                 └────┬────┘                              │  │
│  │                      │                                   │  │
│  │                      ▼                                   │  │
│  │          ┌────────────────────────┐                     │  │
│  │          │   ElastiCache Redis    │                     │  │
│  │          │   (Optional)           │                     │  │
│  │          └────────────────────────┘                     │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                              │
│  ┌───────────────────────────────────────────────────────┐  │
│  │         Public Subnets                                │  │
│  │                                                       │  │
│  │          ┌────────────────────────┐                  │  │
│  │          │   NAT Gateway          │                  │  │
│  │          │   (Outbound Internet)  │                  │  │
│  │          └────────────────────────┘                  │  │
│  └───────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
```

## 🎯 Best Practices

### 1. Right-Size Your Containers

```hcl
# Development: Minimal resources
ecs_cpu           = 256
ecs_memory        = 512
ecs_desired_count = 1

# Production: High availability
ecs_cpu           = 1024
ecs_memory        = 2048
ecs_desired_count = 3  # Spread across AZs
```

### 2. Implement Health Checks

```dockerfile
# In your Dockerfile, add health check endpoint
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1
```

```python
# In your application
@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": time.time()}
```

### 3. Use Environment-Specific Configs

```hcl
locals {
  env_config = {
    dev = {
      cpu           = 256
      memory        = 512
      desired_count = 1
      redis_enabled = false
    }
    staging = {
      cpu           = 512
      memory        = 1024
      desired_count = 2
      redis_enabled = true
    }
    prod = {
      cpu           = 1024
      memory        = 2048
      desired_count = 4
      redis_enabled = true
    }
  }
  config = local.env_config[var.env_alias]
}

module "app" {
  # ...
  ecs_cpu              = local.config.cpu
  ecs_memory           = local.config.memory
  ecs_desired_count    = local.config.desired_count
  create_redis_cluster = local.config.redis_enabled
}
```

### 4. Optimize Docker Images

```dockerfile
# Use multi-stage builds
FROM python:3.11-slim AS builder
WORKDIR /app
COPY requirements.txt .
RUN pip install --user -r requirements.txt

FROM python:3.11-slim
WORKDIR /app
COPY --from=builder /root/.local /root/.local
COPY . .
ENV PATH=/root/.local/bin:$PATH
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

## 💰 Cost Optimization

### Monthly Cost Estimate (US-West-2)

**ECS Fargate Costs**:
| Config | vCPU | Memory (GB) | Per Hour | Per Month (730h) |
|--------|------|-------------|----------|------------------|
| Small | 0.25 | 0.5 | $0.01229 | ~$9 |
| Medium | 0.5 | 1 | $0.02458 | ~$18 |
| Large | 1 | 2 | $0.04916 | ~$36 |
| X-Large | 2 | 4 | $0.09832 | ~$72 |

**Additional Costs**:
- ALB: ~$16/month + $0.008 per LCU-hour
- NAT Gateway: ~$32/month + $0.045/GB processed
- Redis (cache.t3.micro): ~$12/month
- Data Transfer: Varies

**Cost Saving Tips**:
1. Use Spot capacity for non-critical workloads
2. Right-size CPU/memory based on metrics
3. Use VPC endpoints for AWS services
4. Enable container insights selectively

## 🔍 Troubleshooting

### Container Won't Start

**Issue**: Tasks fail to start or immediately stop

**Solutions**:
1. Check CloudWatch Logs:
   ```bash
   aws logs tail /ecs/{product}-{env}-{module} --follow
   ```

2. Verify Dockerfile builds locally:
   ```bash
   docker build -t test .
   docker run -p 8000:8000 test
   ```

3. Check health check endpoint:
   ```bash
   curl http://localhost:8000/health
   ```

### ALB Health Check Failures

**Issue**: Tasks marked unhealthy and replaced

**Solutions**:
1. Verify health check path returns 200:
   ```hcl
   ecs_health_check_endpoint = "/health"  # Must return 200 OK
   ```

2. Increase health check grace period
3. Check security group allows ALB → ECS traffic
4. Review application startup time

### High Memory Usage

**Issue**: Tasks being killed due to OOM

**Solutions**:
```hcl
# Increase memory allocation
ecs_memory = 2048  # Double the memory

# Or optimize application
environment_variables = {
  NODE_OPTIONS = "--max-old-space-size=1536"  # Node.js
  WORKERS      = "2"                          # Reduce workers
}
```

### Cannot Connect to Redis

**Issue**: Application can't reach Redis

**Solutions**:
1. Verify Redis is enabled:
   ```hcl
   create_redis_cluster = true
   ```

2. Check Redis URL in logs (injected as `AK_REDIS_URL`)
3. Verify security groups allow ECS → Redis traffic
4. Ensure both in same VPC

## 📊 Monitoring and Observability

### CloudWatch Metrics

```hcl
# CPU Utilization Alarm
resource "aws_cloudwatch_metric_alarm" "ecs_cpu" {
  alarm_name          = "${var.product_alias}-${var.env_alias}-cpu-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "CPUUtilization"
  namespace           = "AWS/ECS"
  period              = 300
  statistic           = "Average"
  threshold           = 80
  
  dimensions = {
    ClusterName = module.app.cluster_arn
    ServiceName = "${var.product_alias}-${var.env_alias}-${var.module_name}"
  }
}

# Memory Utilization Alarm
resource "aws_cloudwatch_metric_alarm" "ecs_memory" {
  alarm_name          = "${var.product_alias}-${var.env_alias}-memory-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "MemoryUtilization"
  namespace           = "AWS/ECS"
  period              = 300
  statistic           = "Average"
  threshold           = 80
  
  dimensions = {
    ClusterName = module.app.cluster_arn
    ServiceName = "${var.product_alias}-${var.env_alias}-${var.module_name}"
  }
}
```

### Application Logs

Access logs via CloudWatch:
```bash
# Stream logs
aws logs tail /ecs/{product}-{env}-{module} --follow

# Filter logs
aws logs filter-log-events \
  --log-group-name /ecs/{product}-{env}-{module} \
  --filter-pattern "ERROR"
```

## 📚 Additional Resources

- [AWS ECS Documentation](https://docs.aws.amazon.com/ecs/)
- [Fargate Pricing](https://aws.amazon.com/fargate/pricing/)
- [ECS Best Practices](https://docs.aws.amazon.com/AmazonECS/latest/bestpracticesguide/)
- [Application Load Balancer](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/)

## 🔗 Related Modules

- [ECR Module](../common/modules/ecr/) - For building and storing Docker images
- [VPC Module](../common/modules/vpc/) - For custom VPC configurations
- [Redis Module](../common/modules/redis/) - For standalone Redis clusters

---

**Note**: This module automatically provisions VPC, subnets, NAT Gateway, Load Balancer, ECS cluster, and optionally Redis. Ensure your AWS credentials have permissions to create these resources.

## License

Unless otherwise specified, all content, including all source code files and documentation files in this repository are:

Copyright (c) 2025-2026 Yaala Labs.

Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with the License. You may obtain a copy of the License at

http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the License for the specific language governing permissions and limitations under the License.
