# Agent Kernel - GCP Containerized Module

A comprehensive Terraform module for deploying containerized applications on GCP using Cloud Run, with API Gateway, and optional Redis or Firestore integration.

## Overview

This module provides a complete containerized deployment solution on GCP:

- **Cloud Run**: Fully managed container platform with auto-scaling
- **API Gateway**: RESTful API endpoints with custom routing via OpenAPI spec
- **VPC Networking**: Private subnets, Cloud NAT, and VPC Connector
- **State Management**: Optional Memorystore Redis or Firestore for session/state persistence
- **Cloud Logging**: Automatic container logs (no extra setup needed)
- **Automated Build**: Docker image building and Artifact Registry management

Perfect for microservices, web applications, APIs requiring persistent connections, stateful services, and applications needing more resources than Cloud Functions provides.

## Requirements

| Name | Version |
|------|---------|
| Terraform | >= 1.9.5 |
| Google Provider | >= 6.8.0 |
| Docker Provider | >= 3.6.2 |

## Usage

### Basic Containerized API

```hcl
module "container_app" {
  source = "yaalalabs/ak-containerized/google"

  project_id           = "my-gcp-project"
  region               = "us-central1"
  product_alias        = "myapp"
  env_alias            = "prod"
  product_display_name = "My Containerized App"

  module_name  = "api"
  package_path = "${path.module}/src"  # Directory with Dockerfile

  # Cloud Run Configuration
  cpu    = "1"
  memory = "1Gi"
  min_instance_count = 1
  max_instance_count = 10
  container_port     = 8000

  # Health check
  health_check_endpoint = "/health"

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
      path           = "app"
      method         = "GET"
      overwrite_path = "/custom/task"
    },
    {
      path           = "data"
      method         = "POST"
      overwrite_path = "/app/library/data"
    }
  ]

  tags = {
    environment = "production"
    service     = "api"
  }
}

output "api_url" {
  value = module.container_app.agent_invoke_url
}

output "service_url" {
  value = module.container_app.service_url
}
```

### With Existing VPC

```hcl
module "container_app" {
  source = "yaalalabs/ak-containerized/google"

  project_id           = "my-gcp-project"
  region               = "us-central1"
  product_alias        = "myapp"
  env_alias            = "prod"
  product_display_name = "API Service"

  module_name  = "api"
  package_path = "${path.module}/docker"

  # Use existing VPC
  network_id        = "projects/my-project/global/networks/my-vpc"
  private_subnet_id = "projects/my-project/regions/us-central1/subnetworks/private"

  cpu    = "2"
  memory = "2Gi"
  max_instance_count = 20

  environment_variables = {
    DB_HOST = "database.example.com"
    CACHE   = "enabled"
  }

  api_version    = "v2"
  agent_endpoint = "process"
}
```

### With Redis and Firestore

```hcl
module "container_app_stateful" {
  source = "yaalalabs/ak-containerized/google"

  project_id           = "my-gcp-project"
  region               = "us-central1"
  product_alias        = "myapp"
  env_alias            = "prod"
  product_display_name = "Stateful API"

  module_name  = "stateful-api"
  package_path = "${path.module}/app"

  # Enable Redis for caching
  create_redis_cluster = true

  # Enable Firestore for session storage
  create_firestore_database = true

  # Cloud Run Configuration
  cpu                = "2"
  memory             = "4Gi"
  min_instance_count = 2
  max_instance_count = 20
  container_port     = 3000

  environment_variables = {
    NODE_ENV = "production"
    WORKERS  = "4"
    # Redis URL automatically injected as AK_SESSION__REDIS__URL
    # Firestore DB automatically injected as AK_SESSION__FIRESTORE__DATABASE
  }

  api_version    = "v1"
  agent_endpoint = "session"
}
```

### High-Availability Production Setup

```hcl
module "production_app" {
  source = "yaalalabs/ak-containerized/google"

  project_id           = "my-gcp-project"
  region               = "us-central1"
  product_alias        = "enterprise"
  env_alias            = "prod"
  product_display_name = "Enterprise Application"
  is_production        = true

  module_name  = "core-api"
  package_path = "${path.module}/docker"

  # Redis for low-latency session management
  create_redis_cluster = true

  # High-performance Cloud Run
  cpu                = "4"
  memory             = "8Gi"
  min_instance_count = 3   # Always running for low latency
  max_instance_count = 50

  container_port        = 8080
  health_check_endpoint = "/api/health"

  environment_variables = {
    ENVIRONMENT           = "production"
    LOG_LEVEL             = "warn"
    MAX_CONNECTIONS       = "1000"
    ENABLE_METRICS        = "true"
    GRACEFUL_SHUTDOWN_MS  = "30000"
  }

  api_version    = "v1"
  agent_endpoint = "enterprise"

  # Enable MCP server
  enable_mcp_server = true

  tags = {
    environment = "production"
    compliance  = "soc2"
    cost-center = "engineering"
    criticality = "high"
  }
}
```

## Inputs

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|:--------:|
| `project_id` | GCP project ID | `string` | n/a | yes |
| `region` | GCP region for deployment | `string` | n/a | yes |
| `product_alias` | Short identifier for the product | `string` | n/a | yes |
| `env_alias` | Environment identifier (dev, staging, prod) | `string` | n/a | yes |
| `product_display_name` | Human-readable product name | `string` | `"An Agent Kernel deployment"` | no |
| `module_name` | Module name for resource identification | `string` | n/a | yes |
| `is_production` | Production flag (affects VPC connector scaling) | `bool` | `false` | no |
| `package_path` | Path to Docker source directory (with Dockerfile) | `string` | n/a | yes |
| `environment_variables` | Environment variables for container | `map(string)` | `{}` | no |
| `api_version` | API version for endpoint path | `string` | `"v1"` | no |
| `agent_endpoint` | API endpoint name | `string` | `"chat"` | no |
| `api_base_path` | Base path for API | `string` | `"api"` | no |
| `enable_mcp_server` | Enable MCP server and expose MCP API endpoint | `bool` | `false` | no |
| `tags` | Resource labels | `map(string)` | `{}` | no |
| **Cloud Run Configuration** |
| `cpu` | CPU allocation (e.g. "1", "2", "4") | `string` | `"1"` | no |
| `memory` | Memory allocation (e.g. "512Mi", "1Gi", "4Gi") | `string` | `"512Mi"` | no |
| `min_instance_count` | Minimum instances (0 = scale to zero) | `number` | `0` | no |
| `max_instance_count` | Maximum instances | `number` | `10` | no |
| `container_port` | Container port exposed by service | `number` | `8000` | no |
| `health_check_endpoint` | Health check path | `string` | `"/health"` | no |
| **VPC Configuration** |
| `network_id` | Existing VPC network ID (if not creating new) | `string` | `null` | no |
| `private_subnet_id` | Existing private subnet ID | `string` | `null` | no |
| `public_subnet_cidr` | CIDR for public subnet | `string` | `"10.0.1.0/24"` | no |
| `private_subnet_cidr` | CIDR for private subnet | `string` | `"10.0.2.0/24"` | no |
| **State Management** |
| `create_redis_cluster` | Enable Memorystore Redis instance | `bool` | `false` | no |
| `create_firestore_database` | Enable Firestore database for session storage | `bool` | `false` | no |

## Outputs

| Name | Description | Example |
|------|-------------|---------|
| `service_url` | Direct Cloud Run service URL | `https://myapp-prod-api-service-xxxxx-uc.a.run.app` |
| `service_name` | Cloud Run service name | `myapp-prod-api-service` |
| `service_account_email` | Service account email | `myapp-prod-api-run@project.iam.gserviceaccount.com` |
| `gateway_url` | API Gateway base hostname | `myapp-prod-api-gateway-xxxxx.gateway.dev` |
| `api_gateway_id` | API Gateway ID | `myapp-prod-api-api` |
| `agent_invoke_url` | Full HTTPS URL to invoke API | `https://myapp-prod-api-gateway-xxxxx.gateway.dev/api/v1/chat` |

## Features

### Cloud Run

**Fully Managed Containers**:
- No cluster or server management (unlike ECS which needs a cluster)
- Automatic scaling from zero to thousands
- Pay only for actual request processing time
- Built-in load balancing (no ALB needed)
- Rolling deployments with zero downtime

**CPU/Memory Combinations**:
| CPU (vCPU) | Memory Options |
|------------|----------------|
| 1 | 512Mi to 4Gi |
| 2 | 1Gi to 8Gi |
| 4 | 2Gi to 16Gi |
| 8 | 4Gi to 32Gi |

### API Gateway Integration

**API Gateway with OpenAPI Spec**:
```
https://{gateway-id}.gateway.dev/api/{version}/{endpoint}
```

**Features**:
- Declarative routing via OpenAPI spec
- Path rewriting (overwrite_path)
- Automatic HTTPS
- Custom domain support compatible
- No VPC Link needed (simpler than AWS)

### Network Security

**VPC Connector**:
- Cloud Run connects to private resources via VPC Connector
- Only private traffic goes through the connector
- Public internet traffic goes directly (no NAT needed for Cloud Run itself)
- Cloud NAT only used by other VPC resources

**Compared to AWS**:
- No ALB security groups to manage
- No ECS service security groups needed
- VPC Connector handles all private connectivity in one resource

### Redis Integration

**Optional Memorystore Redis**:
- Automatic provisioning when enabled
- Connection URL injected as `AK_SESSION__REDIS__URL`
- Deployed in VPC for secure access
- Transit encryption enabled

### Firestore Integration

**Optional Firestore Database**:
- Automatic provisioning when enabled
- Database name injected as `AK_SESSION__FIRESTORE__DATABASE`
- Project ID injected as `AK_SESSION__FIRESTORE__PROJECT`
- TTL and indexes pre-configured

## Architecture

```
                    ┌─────────────────────┐
                    │   API Gateway       │
                    │   (OpenAPI Spec)    │
                    └──────────┬──────────┘
                               │ HTTPS
                               ▼
                    ┌─────────────────────┐
                    │   Cloud Run         │
                    │   Service           │
                    │                     │
                    │  ┌──────┐ ┌──────┐ │
                    │  │Inst 1│ │Inst 2│ │
                    │  └──┬───┘ └──┬───┘ │
                    │     │        │      │
                    └─────┼────────┼──────┘
                          │        │
                    ┌─────┴────────┴──────┐
                    │   VPC Connector     │
                    │   (10.9.0.0/28)     │
                    └──────────┬──────────┘
                               │
┌──────────────────────────────┼───────────────────────────────┐
│                    VPC       │                                │
│                              │                                │
│  ┌───────────────────────────┼────────────────────────────┐  │
│  │       Private Subnet      │                            │  │
│  │                           ▼                            │  │
│  │          ┌────────────────────────┐                    │  │
│  │          │   Memorystore Redis   │                    │  │
│  │          │   (Optional)          │                    │  │
│  │          └────────────────────────┘                    │  │
│  │                                                        │  │
│  │          ┌────────────────────────┐                    │  │
│  │          │   Firestore           │                    │  │
│  │          │   (Optional)          │                    │  │
│  │          └────────────────────────┘                    │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                               │
│  ┌────────────────────────────────────────────────────────┐  │
│  │       Public Subnet                                    │  │
│  │          ┌────────────────────────┐                    │  │
│  │          │   Cloud NAT           │                    │  │
│  │          │   (Outbound Internet) │                    │  │
│  │          └────────────────────────┘                    │  │
│  └────────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────┘
```

Notice how much simpler this is compared to AWS:
- No ALB (Cloud Run has built-in load balancing)
- No VPC Link (VPC Connector handles private access)
- No security groups (IAM + VPC Connector)
- No ECS Cluster (Cloud Run is fully managed)

## Best Practices

### 1. Right-Size Your Containers

```hcl
# Development: Minimal resources, scale to zero
cpu                = "1"
memory             = "512Mi"
min_instance_count = 0   # Scale to zero when idle

# Production: Always-on for low latency
cpu                = "2"
memory             = "2Gi"
min_instance_count = 2   # Always keep 2 instances warm
max_instance_count = 20
```

### 2. Implement Health Checks

```dockerfile
# In your Dockerfile
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
      cpu             = "1"
      memory          = "512Mi"
      min_instances   = 0
      max_instances   = 5
      redis_enabled   = false
    }
    staging = {
      cpu             = "1"
      memory          = "1Gi"
      min_instances   = 1
      max_instances   = 10
      redis_enabled   = true
    }
    prod = {
      cpu             = "2"
      memory          = "2Gi"
      min_instances   = 2
      max_instances   = 50
      redis_enabled   = true
    }
  }
  config = local.env_config[var.env_alias]
}

module "app" {
  # ...
  cpu                = local.config.cpu
  memory             = local.config.memory
  min_instance_count = local.config.min_instances
  max_instance_count = local.config.max_instances
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

## Cost Optimization

### Monthly Cost Estimate (us-central1)

**Cloud Run Costs** (pay per use):
| Config | vCPU | Memory | Per vCPU-sec | Per GiB-sec | Idle Cost |
|--------|------|--------|--------------|-------------|-----------|
| Small | 1 | 512Mi | $0.00002400 | $0.00000250 | $0 (scale to zero) |
| Medium | 2 | 1Gi | $0.00002400 | $0.00000250 | $0 (scale to zero) |
| Large | 4 | 4Gi | $0.00002400 | $0.00000250 | $0 (scale to zero) |

**Key advantage**: With `min_instance_count = 0`, you pay nothing when there's no traffic. AWS ECS Fargate charges even when idle.

**Additional Costs**:
- VPC Connector: ~$7/month per instance (min 2)
- Cloud NAT: ~$1/month + $0.045/GB processed
- Memorystore Redis (basic, 1GB): ~$35/month
- API Gateway: $3 per million calls
- Artifact Registry: $0.10/GB storage

**Cost Saving Tips**:
1. Use `min_instance_count = 0` for dev/staging (scale to zero)
2. Right-size CPU/memory based on Cloud Run metrics
3. Use `PRIVATE_RANGES_ONLY` egress to minimize VPC Connector traffic
4. Clean up old container images in Artifact Registry

## Troubleshooting

### Container Won't Start

**Issue**: Revision fails to deploy or immediately crashes

**Solutions**:
1. Check Cloud Logging:
   ```bash
   gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name={service-name}" --limit=50
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

### Health Check Failures

**Issue**: Instances marked unhealthy and replaced

**Solutions**:
1. Verify health check path returns 200:
   ```hcl
   health_check_endpoint = "/health"  # Must return 200 OK
   ```

2. Increase startup probe timeout (slow apps)
3. Check container port matches `container_port` variable
4. Review application startup time

### Cannot Connect to Redis

**Issue**: Application can't reach Memorystore Redis

**Solutions**:
1. Verify Redis is enabled:
   ```hcl
   create_redis_cluster = true
   ```

2. Check Redis URL in logs (injected as `AK_SESSION__REDIS__URL`)
3. Verify VPC Connector is active:
   ```bash
   gcloud compute networks vpc-access connectors describe {connector-name} --region={region}
   ```
4. Ensure Redis and VPC Connector are in the same network

### API Gateway Returns 403

**Issue**: Requests to API Gateway return forbidden

**Solutions**:
1. Verify the service is public:
   ```bash
   gcloud run services get-iam-policy {service-name} --region={region}
   ```
2. Check the OpenAPI spec matches your endpoints
3. Verify the API config was deployed successfully

## Cross-Cloud Comparison

| Feature | AWS (ECS) | GCP (Cloud Run) |
|---------|-----------|-----------------|
| Container Runtime | ECS Fargate | Cloud Run |
| Cluster Management | ECS Cluster needed | Not needed |
| Load Balancer | ALB (separate resource) | Built-in |
| API Gateway | HTTP API v2 + VPC Link | API Gateway + OpenAPI |
| Private Access | Security Groups | VPC Connector |
| Scaling | Autoscaling Policy | Automatic (built-in) |
| Scale to Zero | Not supported | Supported |
| Logging | CloudWatch (manual setup) | Cloud Logging (automatic) |
| Docker Registry | ECR | Artifact Registry |
| Session Storage | DynamoDB | Firestore |

## Related Modules

- [Artifact Registry Module](../common/modules/artifact-registry/) - For building and storing Docker images
- [VPC Module](../common/modules/vpc/) - For custom VPC configurations
- [Memorystore Module](../common/modules/memorystore/) - For standalone Redis instances
- [Firestore Module](../common/modules/firestore/) - For standalone Firestore databases

---

**Note**: This module automatically provisions VPC, subnets, Cloud NAT, Cloud Run service, VPC Connector, and optionally Redis/Firestore. Ensure your GCP project has the required APIs enabled (Cloud Run, VPC Access, API Gateway, Artifact Registry).

## License

Unless otherwise specified, all content, including all source code files and documentation files in this repository are:

Copyright (c) 2025-2026 Yaala Labs.

Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with the License. You may obtain a copy of the License at

http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the License for the specific language governing permissions and limitations under the License.
