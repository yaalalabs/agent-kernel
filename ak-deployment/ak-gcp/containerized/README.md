# Agent Kernel - GCP Containerized Module

A comprehensive Terraform module for deploying containerized applications on GCP using Cloud Run with always-on capability (min_instance_count≥1), API Gateway, and optional state management with Memorystore Redis or Firestore.

## 📋 Overview

This module provides a complete containerized deployment solution on GCP:

- 🐳 **Cloud Run**: Fully managed container platform with always-on capability (min_instance_count defaults to 1)
- 🌐 **API Gateway**: OpenAPI-based routing with versioned endpoints and JWT authorization support
- 🔄 **Flexible Deployment**: Automatic Docker image build and push to Artifact Registry
- 🔒 **VPC Integration**: VPC Connector for private networking with Redis and Firestore
- 💾 **State Management**: Optional Memorystore Redis or Firestore for session/state persistence
- 📊 **Cloud Logging**: Built-in logging and monitoring (no extra configuration needed)
- 🏗️ **Automated Infrastructure**: VPC, subnets, NAT Gateway, and firewall rules created automatically

Perfect for microservices, web applications, APIs requiring persistent connections, stateful services, and applications needing guaranteed availability without cold starts.

**Key Difference from Serverless**: This module defaults to `min_instance_count = 1` (always-on, no cold starts), while the serverless module defaults to `min_instance_count = 0` (scale-to-zero). Both use Cloud Run, but with different scaling configurations.

## 📋 Requirements

| Name | Version |
|------|---------|
| Terraform | >= 1.9.5 |
| Google Provider | >= 6.8.0 |
| Google Beta Provider | >= 6.8.0 |
| Docker Provider | 3.6.2 |

## 🚀 Usage

### Basic Containerized API

```hcl
module "container_app" {
  source = "../containerized"

  project_id           = "my-gcp-project"
  region               = "us-central1"
  product_alias        = "myapp"
  env_alias            = "prod"
  product_display_name = "My Containerized App"
  
  module_name  = "api"
  package_path = "${path.module}/src"  # Directory with Dockerfile
  
  # Cloud Run Configuration (always-on by default)
  cpu                = "1"
  memory             = "1Gi"
  min_instance_count = 1   # Always keep at least 1 instance running (no cold starts)
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


### With Memorystore Redis for Session Storage

```hcl
module "container_app_redis" {
  source = "../containerized"

  project_id           = "my-gcp-project"
  region               = "us-central1"
  product_alias        = "myapp"
  env_alias            = "prod"
  product_display_name = "Containerized API with Redis"
  
  module_name  = "chat"
  package_path = "${path.module}/dist"
  
  # Enable Memorystore Redis for session storage
  create_redis_cluster = true
  
  cpu                = "1"
  memory             = "512Mi"
  min_instance_count = 1  # Always-on for low latency
  
  environment_variables = {
    ENVIRONMENT = "production"
    # Redis URL automatically injected as AK_SESSION__REDIS__URL
  }
  
  api_version    = "v1"
  agent_endpoint = "chat"
}
```

### With Firestore for Session Storage

```hcl
module "container_app_firestore" {
  source = "../containerized"

  project_id           = "my-gcp-project"
  region               = "us-central1"
  product_alias        = "myapp"
  env_alias            = "prod"
  product_display_name = "Containerized API with Firestore"
  
  module_name  = "chat"
  package_path = "${path.module}/dist"
  
  # Enable Firestore for session storage
  create_firestore_database = true
  
  environment_variables = {
    ENVIRONMENT = "production"
    # Firestore connection details automatically injected:
    # AK_SESSION__FIRESTORE__DATABASE_ID
    # AK_SESSION__FIRESTORE__PROJECT_ID
    # AK_SESSION__FIRESTORE__COLLECTION_NAME
  }
  
  api_version    = "v1"
  agent_endpoint = "chat"
}
```


### With Existing VPC

```hcl
module "container_app_vpc" {
  source = "../containerized"

  project_id           = "my-gcp-project"
  region               = "us-central1"
  product_alias        = "myapp"
  env_alias            = "prod"
  product_display_name = "Containerized API with Existing VPC"
  
  module_name  = "api"
  package_path = "${path.module}/dist"
  
  # Use existing VPC instead of creating new one
  network_id        = "projects/my-project/global/networks/my-vpc"
  private_subnet_id = "projects/my-project/regions/us-central1/subnetworks/private-subnet"
  
  # Specify connector CIDR that doesn't overlap with existing subnets
  connector_cidr = "10.9.1.0/28"
  
  create_redis_cluster = true
  
  cpu                = "2"
  memory             = "2Gi"
  min_instance_count = 2
  max_instance_count = 20
  
  api_version    = "v1"
  agent_endpoint = "chat"
}
```

### Production Setup with High Availability

```hcl
module "production_app" {
  source = "../containerized"

  project_id           = "enterprise-gcp-project"
  region               = "us-central1"
  product_alias        = "enterprise"
  env_alias            = "prod"
  product_display_name = "Enterprise Production API"
  is_production        = true

  module_name  = "core-api"
  package_path = "${path.module}/dist"

  # Keep multiple instances warm for high availability
  min_instance_count = 3
  max_instance_count = 50

  # High performance configuration
  cpu     = "4"
  memory  = "8Gi"
  timeout = 300

  # Enable both Redis and Firestore
  create_redis_cluster      = true
  create_firestore_database = true

  # API throttling
  throttling_rate_limit  = 100  # requests per second
  throttling_burst_limit = 200  # burst capacity

  environment_variables = {
    ENVIRONMENT    = "production"
    LOG_LEVEL      = "warn"
    ENABLE_METRICS = "true"
  }

  api_version    = "v1"
  agent_endpoint = "enterprise"

  tags = {
    environment = "production"
    compliance  = "SOC2"
    cost_center = "engineering"
    criticality = "high"
  }
}
```

## 📥 Inputs

### Core Configuration

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|:--------:|
| `project_id` | GCP project ID | `string` | n/a | yes |
| `region` | GCP region for deployment | `string` | n/a | yes |
| `product_alias` | Short identifier for the product | `string` | n/a | yes |
| `env_alias` | Environment identifier (dev, staging, prod) | `string` | n/a | yes |
| `product_display_name` | Human-readable product name | `string` | `"An Agent Kernel deployment"` | no |
| `module_name` | Module name for resource identification | `string` | n/a | yes |
| `is_production` | Enable production features | `bool` | `false` | no |
| `package_path` | Path to Docker build context (dist/ directory with Dockerfile) | `string` | n/a | yes |
| `environment_variables` | Environment variables for the container | `map(string)` | `{}` | no |
| `tags` | Resource labels for GCP resources | `map(string)` | `{}` | no |

### Cloud Run Configuration

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|:--------:|
| `cpu` | CPU allocation (e.g. '1' = 1 vCPU, '2' = 2 vCPUs, '4' = 4 vCPUs) | `string` | `"1"` | no |
| `memory` | Memory allocation (e.g. '512Mi', '1Gi', '2Gi', '8Gi') | `string` | `"512Mi"` | no |
| `timeout` | Maximum request timeout in seconds (max 3600) | `number` | `30` | no |
| `min_instance_count` | Minimum instances (1 = always-on, no cold starts) | `number` | `1` | no |
| `max_instance_count` | Maximum number of instances | `number` | `10` | no |
| `container_port` | Port the container listens on | `number` | `8000` | no |
| `health_check_endpoint` | Health check path | `string` | `"/health"` | no |

**Key Feature**: `min_instance_count = 1` enables always-on behavior (no cold starts). Set to 0 to enable scale-to-zero (serverless behavior).

### API Gateway Configuration

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|:--------:|
| `api_version` | API version for endpoint path (e.g. 'v1', 'v2') | `string` | `"v1"` | no |
| `agent_endpoint` | Default API endpoint name | `string` | `"chat"` | no |
| `api_base_path` | Base path segment for API | `string` | `"api"` | no |
| `backend_deadline` | API Gateway backend deadline in seconds (must be <= timeout) | `number` | `30` | no |
| `gateway_endpoints` | Additional API endpoints to expose | `list(object)` | `[]` | no |
| `enable_mcp_server` | Enable MCP server and expose /mcp API endpoint | `bool` | `false` | no |

**Gateway Endpoints Object Structure**:
```hcl
gateway_endpoints = [
  {
    path           = "health"        # Path segment (without leading /)
    method         = "GET"           # HTTP method: GET, POST, PUT, DELETE, PATCH, ANY
    overwrite_path = "/health"       # Target path on Cloud Run service
  }
]
```

### Network Configuration

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|:--------:|
| `network_id` | VPC network ID. If null, a new VPC is created | `string` | `null` | no |
| `private_subnet_id` | Private subnet ID (when using existing VPC) | `string` | `null` | no |
| `connector_cidr` | CIDR block for VPC Access Connector. If null, auto-computed (e.g. '10.9.1.0/28') | `string` | `null` | no |
| `public_subnet_cidr` | CIDR for public subnet (when creating new VPC) | `string` | `"10.0.1.0/24"` | no |
| `private_subnet_cidr` | CIDR for private subnet (when creating new VPC) | `string` | `"10.0.2.0/24"` | no |

**VPC Connector**: Required for Cloud Run to access private resources (Redis, Firestore). The connector CIDR must not overlap with existing subnets.

### State Management Configuration

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|:--------:|
| `create_redis_cluster` | Create Memorystore Redis instance for agent memory | `bool` | `false` | no |
| `create_firestore_database` | Create Firestore database for agent session storage | `bool` | `false` | no |

**Redis Environment Variables (Auto-injected when enabled)**:
- `AK_SESSION__REDIS__URL`: Complete Redis connection URL with authentication

**Firestore Environment Variables (Auto-injected when enabled)**:
- `AK_SESSION__FIRESTORE__DATABASE_ID`: Firestore database ID
- `AK_SESSION__FIRESTORE__PROJECT_ID`: GCP project ID
- `AK_SESSION__FIRESTORE__COLLECTION_NAME`: Collection name for session storage

### CORS Configuration

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|:--------:|
| `enable_cors` | Enable CORS pre-flight OPTIONS handling in API Gateway | `bool` | `true` | no |
| `cors_allow_origins` | CORS allowed origins (enforce in Cloud Run app) | `list(string)` | `["*"]` | no |
| `cors_allow_methods` | CORS allowed methods | `list(string)` | `["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"]` | no |
| `cors_allow_headers` | CORS allowed headers | `list(string)` | `["*"]` | no |
| `cors_expose_headers` | CORS exposed headers | `list(string)` | `[]` | no |
| `cors_max_age` | CORS pre-flight cache max age in seconds | `number` | `600` | no |
| `cors_allow_credentials` | Whether to allow credentials in CORS requests | `bool` | `false` | no |

**Note**: GCP API Gateway does not have native CORS handling like AWS API Gateway v2. When `enable_cors = true`, OPTIONS pre-flight handlers are added to the OpenAPI spec. The actual CORS response headers (Access-Control-Allow-*) must be set by your Cloud Run application (via FastAPI middleware or similar).

### Security Configuration

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|:--------:|
| `allow_unauthenticated_invocation` | Allow unauthenticated direct invocation of Cloud Run service URL | `bool` | `true` | no |
| `authorizer` | JWT authorizer configuration for API Gateway | `object` | `null` | no |

**Authorizer Object Structure**:
```hcl
authorizer = {
  issuer    = "https://accounts.google.com"                      # JWT issuer URL
  jwks_uri  = "https://www.googleapis.com/oauth2/v3/certs"      # JWKS endpoint
  audiences = ["your-client-id.apps.googleusercontent.com"]     # Expected JWT audiences
}
```

When `authorizer` is set, API Gateway validates JWT tokens in every request before forwarding to Cloud Run.

### Throttling Configuration

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|:--------:|
| `throttling_rate_limit` | Steady-state request rate limit per second. Set null to disable | `number` | `null` | no |
| `throttling_burst_limit` | Burst request limit (token bucket size). Set null to disable | `number` | `null` | no |

**Note**: Both values must be provided to enable throttling. Set both to `null` to disable.

### Logging Configuration

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|:--------:|
| `log_retention_days` | Log retention in days for Cloud Logging. If set, updates project default log bucket retention | `number` | `null` | no |

## 📤 Outputs

| Name | Description | Example |
|------|-------------|---------|
| `service_url` | Direct Cloud Run service URL | `https://myapp-prod-api-svc-abc123.run.app` |
| `service_name` | Cloud Run service name | `myapp-prod-api-svc` |
| `service_account_email` | Service account email used by Cloud Run | `myapp-prod-api-fn@project.iam.gserviceaccount.com` |
| `gateway_url` | API Gateway base URL | `myapp-prod-api-12345678-gw-abc123.uc.gateway.dev` |
| `api_gateway_id` | API Gateway ID | `myapp-prod-api-12345678-api` |
| `agent_invoke_url` | Full agent invocation URL via API Gateway | `https://myapp-prod-api-12345678-gw-abc123.uc.gateway.dev/api/v1/chat` |
| `authorizer_status` | JWT authorizer configuration status | `"JWT Authorizer configured (issuer: ...)"` or `"No authorizer configured — endpoints are publicly accessible"` |

## ✨ Features

### 🐳 Cloud Run Always-On

**No Cold Starts**:
- **min_instance_count = 1**: At least one instance always running (no cold starts)
- **Immediate Response**: First request experiences no startup latency
- **Scale-Up Option**: Set `min_instance_count >= 2` for high availability

**Automatic Scaling**:
- Scales from `min_instance_count` to `max_instance_count` based on request load
- Each instance handles multiple concurrent requests
- Automatic scale-down when traffic decreases

**Resource Configuration**:
- CPU: 1, 2, 4, 6, or 8 vCPUs
- Memory: 128Mi to 32Gi (must match CPU limits)
- Timeout: Up to 3600 seconds (1 hour)

**Container Platform**:
- Automatic Docker image build from source directory
- Push to Artifact Registry
- Deploy to Cloud Run with zero-downtime updates

### 🌐 API Gateway Integration

**OpenAPI-Based Routing**:
```
https://{gateway-id}.{region}.gateway.dev/{api_base_path}/{version}/{endpoint}
```

**Example**: `https://myapp-prod-api-12345678-gw-abc123.uc.gateway.dev/api/v1/chat`

**Features**:
- OpenAPI 2.0 (Swagger) specification
- ESPv2 (Extensible Service Proxy) for routing
- Path rewriting to Cloud Run service
- Configurable backend deadline
- JWT authorization support
- Request throttling with quota management

**Default Endpoints**:
- `POST /{api_base_path}/{version}/{agent_endpoint}` → `/api/v1/chat`
- `POST /{api_base_path}/{version}/{agent_endpoint}-multipart` → `/api/v1/chat-multipart`

**Custom Endpoints**:
- Define additional endpoints via `gateway_endpoints`
- Support for GET, POST, PUT, DELETE, PATCH, ANY methods
- Path rewriting for flexible routing

### 🔒 Network Security and VPC Integration

**VPC Connector Architecture**:
- Serverless VPC Access Connector enables Cloud Run to access private resources
- Connector CIDR: Auto-computed or manually specified (must be /28)
- Firewall rules automatically created for connector traffic

**Private Resource Access**:
- Memorystore Redis via private IP
- Firestore via private endpoint
- Other VPC resources via private networking

**Security Features**:
- Service Account with least-privilege IAM roles
- Optional JWT authorization at API Gateway
- Configurable Cloud Run invocation permissions
- VPC firewall rules for network isolation

### 💾 State Management Options

#### Memorystore Redis Integration
**When `create_redis_cluster = true`**:
- Memorystore for Redis (managed Redis service)
- Basic tier (1GB) for development
- Standard tier (5GB+) for production with HA
- Private IP connectivity via VPC Connector
- Connection URL automatically injected as `AK_SESSION__REDIS__URL`

#### Firestore Integration
**When `create_firestore_database = true`**:
- Firestore in Native mode (GCP equivalent of DynamoDB)
- Document-based NoSQL database
- Automatic scaling and high availability
- Connection details automatically injected:
  - `AK_SESSION__FIRESTORE__DATABASE_ID`
  - `AK_SESSION__FIRESTORE__PROJECT_ID`
  - `AK_SESSION__FIRESTORE__COLLECTION_NAME`

## 🏗️ Architecture

**Cloud Run Always-On with No Cold Starts**:

```
                        ┌─────────────────────┐
                        │   Internet          │
                        └──────────┬──────────┘
                                   │ HTTPS
                                   ▼
┌─────────────────────────────────────────────────────────────┐
│                API Gateway (ESPv2)                          │
│              OpenAPI 2.0 Specification                      │
│                                                             │
│              • JWT Authorization (optional)                 │
│              • Request Throttling (optional)                │
│              • Path Rewriting                               │
│              • CORS Pre-flight Handling                     │
└─────────────────────┬───────────────────────────────────────┘
                      │ Backend Deadline
                      │ Routes to Cloud Run
                      ▼
┌──────────────────────────────────────────────────────────────┐
│                   Cloud Run Service                          │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐ │
│  │         Container Instances (Always-On)                 │ │
│  │         • min_instance_count = 1 (no cold starts)      │ │
│  │         • max_instance_count = 10                      │ │
│  │         • CPU: 1 vCPU, Memory: 512Mi                   │ │
│  │         • Timeout: 30s                                 │ │
│  │         • Service Account Identity                     │ │
│  │                                                        │ │
│  │  ┌─────────────────────────────────────────────────┐  │ │
│  │  │     Docker Container                            │  │ │
│  │  │     • Built from package_path                   │  │ │
│  │  │     • Pushed to Artifact Registry               │  │ │
│  │  │     • Listens on port 8000                      │  │ │
│  │  │     • Health check: /health                     │  │ │
│  │  └─────────────────────────────────────────────────┘  │ │
│  └────────────────────────────────────────────────────────┘ │
│                           │                                  │
│                           │ VPC Connector                    │
│                           ▼                                  │
└──────────────────────────────────────────────────────────────┘
                            │
┌───────────────────────────┼───────────────────────────────────┐
│                    VPC Network                                │
│                           │                                   │
│  ┌────────────────────────┼────────────────────────────────┐ │
│  │    VPC Access Connector (10.9.0.0/28)                   │ │
│  │    • Enables Cloud Run → VPC connectivity               │ │
│  │    • Auto-computed CIDR to avoid conflicts              │ │
│  │    • Firewall rules for connector traffic               │ │
│  └────────────────────────┼────────────────────────────────┘ │
│                           │                                   │
│  ┌────────────────────────┼────────────────────────────────┐ │
│  │       Private Subnet (10.0.2.0/24)                      │ │
│  │                       │                                  │ │
│  │          ┌────────────┴────────────┐                    │ │
│  │          │                         │                    │ │
│  │          ▼                         ▼                    │ │
│  │  ┌──────────────────┐    ┌──────────────────┐          │ │
│  │  │ Memorystore      │    │   Firestore      │          │ │
│  │  │ Redis            │    │   Database       │          │ │
│  │  │ (Optional)       │    │   (Optional)     │          │ │
│  │  └──────────────────┘    └──────────────────┘          │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                               │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │       Public Subnet (10.0.1.0/24)                       │ │
│  │                                                          │ │
│  │          ┌────────────────────────┐                     │ │
│  │          │   Cloud NAT            │                     │ │
│  │          │   (Outbound Internet)  │                     │ │
│  │          └────────────────────────┘                     │ │
│  └─────────────────────────────────────────────────────────┘ │
└───────────────────────────────────────────────────────────────┘

                      Traffic Flow:
                      1. Internet → API Gateway
                      2. API Gateway → Cloud Run (JWT validation, throttling)
                      3. Cloud Run → VPC Connector
                      4. VPC Connector → Redis/Firestore (private IP)
                      5. Response flows back through API Gateway
```

**Key Architecture Points**:
- **Always-On**: `min_instance_count = 1` means at least one instance always running (no cold starts)
- **Immediate Response**: First request experiences no startup latency
- **VPC Connector**: Required for Cloud Run to access private resources
- **Automatic CIDR**: Connector CIDR auto-computed to avoid conflicts
- **Service Account**: Dedicated identity with least-privilege IAM roles

## 🎯 Best Practices

### 1. Right-Size Your Cloud Run Service

```hcl
# Light API calls (simple responses)
cpu    = "1"
memory = "512Mi"
timeout = 10

# Data processing (moderate compute)
cpu    = "2"
memory = "2Gi"
timeout = 60

# Heavy compute (ML inference, large data)
cpu    = "4"
memory = "8Gi"
timeout = 300
```

**CPU-Memory Pairing**:
- 1 vCPU: 128Mi - 4Gi
- 2 vCPU: 512Mi - 8Gi
- 4 vCPU: 2Gi - 16Gi
- 8 vCPU: 4Gi - 32Gi

### 2. Optimize Docker Images

```dockerfile
# Use multi-stage builds
FROM python:3.12-slim as builder
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

FROM python:3.12-slim
WORKDIR /app
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY . .
CMD ["python", "app.py"]
```

**Tips**:
- Use slim base images
- Minimize layers
- Exclude unnecessary files (.dockerignore)
- Cache dependencies

### 3. Environment-Specific Configuration

```hcl
locals {
  config = {
    dev = {
      cpu                = "1"
      memory             = "512Mi"
      min_instance_count = 1  # Always-on for dev convenience
      max_instance_count = 5
      create_redis       = false
      create_firestore   = true
    }
    prod = {
      cpu                = "4"
      memory             = "8Gi"
      min_instance_count = 3  # Multiple instances for HA
      max_instance_count = 50
      create_redis       = true
      create_firestore   = true
    }
  }
  env_config = local.config[var.env_alias]
}

module "api" {
  source = "../containerized"

  # ... other config
  cpu                       = local.env_config.cpu
  memory                    = local.env_config.memory
  min_instance_count        = local.env_config.min_instance_count
  max_instance_count        = local.env_config.max_instance_count
  create_redis_cluster      = local.env_config.create_redis
  create_firestore_database = local.env_config.create_firestore
}
```

### 4. Health Check Implementation

```python
# Python FastAPI example
from fastapi import FastAPI

app = FastAPI()

@app.get("/health")
def health_check():
    return {"status": "healthy", "service": "api"}

@app.get("/api/v1/chat")
def chat_endpoint():
    # Your chat logic
    return {"response": "Hello"}
```

### 5. Production Checklist

✅ Set `min_instance_count >= 1` for always-on behavior (no cold starts)  
✅ Configure JWT authorization for API Gateway  
✅ Enable request throttling for rate limiting  
✅ Set `allow_unauthenticated_invocation = false` for stricter security  
✅ Use appropriate CPU and memory for workload  
✅ Configure Cloud Logging retention  
✅ Enable both Redis and Firestore for redundancy  
✅ Use existing VPC for network isolation  
✅ Set proper IAM roles and permissions  
✅ Test with realistic load  

### 6. CORS Configuration

```hcl
# Enable CORS in Terraform
module "api" {
  # ... other config
  enable_cors = true
  cors_allow_origins = ["https://myapp.com", "https://app.myapp.com"]
  cors_allow_methods = ["GET", "POST", "PUT", "DELETE", "OPTIONS"]
  cors_allow_headers = ["Content-Type", "Authorization"]
}
```

```python
# Enforce CORS in FastAPI application
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://myapp.com", "https://app.myapp.com"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
    expose_headers=["X-Request-ID"],
    max_age=600,
)
```

**Note**: GCP API Gateway handles OPTIONS pre-flight requests, but your Cloud Run application must set the actual CORS response headers.

## 💰 Cost Optimization

### Monthly Cost Estimate (us-central1)

**Cloud Run Pricing**:
```
CPU: $0.00002400 per vCPU-second
Memory: $0.00000250 per GiB-second
Requests: $0.40 per million requests

Example: 1M requests/month, 200ms avg execution, 512Mi memory, 0.5 vCPU:
- CPU cost: 1,000,000 × 0.2s × 0.5 vCPU × $0.000024 = $2.40
- Memory cost: 1,000,000 × 0.2s × 0.5 GiB × $0.0000025 = $0.25
- Request cost: 1,000,000 × $0.0000004 = $0.40
- Total: ~$3.05/month
```

**Idle Cost with Always-On**:
```
With min_instance_count = 1:
- CPU idle: 1 vCPU × 730 hours/month × $0.000024 = $17.52/month
- Memory idle: 0.5 GiB × 730 hours/month × $0.0000025 = $0.91/month
- Total idle cost: ~$18.43/month (even with zero requests)
```

**Additional Costs**:
- **VPC Connector**: ~$7/month per instance (min 2 for HA) = ~$14/month
- **Cloud NAT**: ~$1/month + $0.045/GB processed
- **Memorystore Redis** (Basic, 1GB): ~$35/month
- **Memorystore Redis** (Standard, 5GB with HA): ~$175/month
- **Firestore**: Pay per read/write/delete operation
  - Document reads: $0.06 per 100,000
  - Document writes: $0.18 per 100,000
  - Document deletes: $0.02 per 100,000
- **API Gateway**: $3 per million calls
- **Artifact Registry**: $0.10/GB storage per month
- **Cloud Logging**: First 50 GB/month free, then $0.50/GB

### Cost Comparison Table

| Configuration | Cloud Run (idle) | Cloud Run (requests) | VPC Connector | Redis | Firestore | API Gateway | Total/Month |
|---------------|-----------------|---------------------|---------------|-------|-----------|-------------|-------------|
| Dev (1 warm instance, Firestore) | $18 | $3 | $14 | $0 | ~$5 | $3 | ~$43 |
| Staging (1 warm instance, Redis) | $18 | $10 | $14 | $35 | $0 | $10 | ~$87 |
| Production (3 warm, Redis HA) | $55 | $30 | $14 | $175 | $10 | $30 | ~$314 |

### Cost-Saving Tips

1. **Use Scale-to-Zero for Development**
   ```hcl
   min_instance_count = 0  # No idle cost, but cold starts
   ```
   Consider using the serverless module for development to save costs.

2. **Right-Size Resources**
   - Monitor Cloud Run metrics to find optimal CPU/memory
   - Reduce timeout to minimum needed
   - Use smaller memory allocations when possible

3. **Choose State Management Wisely**
   - **Firestore**: Better for variable workloads (pay per operation)
   - **Redis**: Better for high-frequency access (fixed cost)
   - Use Redis Basic tier for development

4. **Optimize VPC Connector Usage**
   - Share one VPC Connector across multiple Cloud Run services
   - Use existing VPC when possible

5. **Clean Up Unused Resources**
   ```bash
   # List old container images
   gcloud artifacts docker images list \
     ${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPOSITORY}

   # Delete old images
   gcloud artifacts docker images delete \
     ${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPOSITORY}/image@sha256:...
   ```

## 🔍 Troubleshooting

### Common Issues

1. **Cold Starts**
   - If experiencing cold starts with `min_instance_count = 1`, check instance health
   - Verify the service is receiving traffic to keep instances warm
   - Consider increasing `min_instance_count` for high-traffic scenarios

2. **High Idle Costs**
   - Monitor Cloud Run metrics to understand idle time
   - Consider using the serverless module (`min_instance_count = 0`) for development
   - Reduce `min_instance_count` during low-traffic periods

3. **VPC Connector Issues**
   - Verify connector CIDR does not overlap with existing subnets
   - Check firewall rules allow traffic from connector to private resources
   - Ensure connector is in the same region as Cloud Run

4. **Redis Connection Issues**
   - Verify Redis instance is in `READY` state
   - Check VPC Connector is properly configured
   - Ensure Redis is in the same region as Cloud Run
   - Verify the service account has necessary IAM roles

5. **API Gateway Routing Issues**
   - Verify the OpenAPI specification is valid
   - Check backend service URL is correct
   - Ensure Cloud Run service is accessible
   - Review API Gateway logs for routing errors

### Debugging Commands

```bash
# Check Cloud Run service status
gcloud run services describe ${SERVICE_NAME} --region=${REGION}

# View Cloud Run logs
gcloud logging read "resource.type=cloud_run_revision" \
  --resource-labels service_name=${SERVICE_NAME} \
  --limit 50

# Check VPC Connector status
gcloud compute networks vpc-access connectors describe ${CONNECTOR_NAME} \
  --region=${REGION}

# Check Redis instance status
gcloud redis instances describe ${REDIS_NAME} --region=${REGION}

# Test API Gateway endpoint
curl -X POST ${API_URL} \
  -H "Content-Type: application/json" \
  -d '{"message": "test", "session_id": "debug"}'
```

## 📞 Support

For issues, questions, or contributions, please refer to the main repository's issue tracker.

---

## License

Unless otherwise specified, all content, including all source code files and documentation files in this repository are:

Copyright (c) 2025-2026 Yaala Labs.

Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with the License. You may obtain a copy of the License at

http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the License for the specific language governing permissions and limitations under the License.
