# Agent Kernel - GCP Serverless Module

A comprehensive Terraform module for deploying serverless applications on GCP using Cloud Run with scale-to-zero capability, API Gateway, and optional state management with Memorystore Redis or Firestore.

## 📋 Overview

This module provides a complete serverless deployment solution on GCP:

- ⚡ **Cloud Run**: Serverless containers with scale-to-zero (min_instance_count=0) — no idle cost, cold starts on first request
- 🌐 **API Gateway**: OpenAPI-based routing with versioned endpoints and JWT authorization support
- 🔄 **Flexible Deployment**: Automatic Docker image build and push to Artifact Registry
- 🔒 **VPC Integration**: VPC Connector for private networking with Redis and Firestore
- 💾 **State Management**: Optional Memorystore Redis or Firestore for session/state persistence
- 📊 **Cloud Logging**: Built-in logging and monitoring (no extra configuration needed)
- 🏗️ **Automated Infrastructure**: VPC, subnets, NAT Gateway, and firewall rules created automatically

Perfect for microservices, API backends, event-driven architectures, and serverless web applications requiring REST endpoints with enterprise API management.

## 📋 Requirements

| Name | Version |
|------|---------|
| Terraform | >= 1.9.5 |
| Google Provider | >= 6.8.0 |
| Google Beta Provider | >= 6.8.0 |
| Docker Provider | 3.6.2 |

## 🚀 Usage

### Basic Serverless Deployment

```hcl
module "serverless_agent" {
  source = "yaalalabs/ak-serverless/google"

  project_id           = "my-gcp-project"
  region               = "us-central1"
  product_alias        = "myapp"
  env_alias            = "prod"
  product_display_name = "My Application API"
  
  module_name  = "api"
  package_path = "${path.module}/dist"
  
  cpu    = "1"
  memory = "512Mi"
  timeout = 30
  
  environment_variables = {
    ENVIRONMENT = "production"
    LOG_LEVEL   = "info"
  }
  
  # API Gateway
  api_version    = "v1"
  api_base_path  = "api"
  agent_endpoint = "chat"
  
  tags = {
    environment = "production"
    service     = "api"
  }
}

output "api_url" {
  value = module.serverless_agent.agent_invoke_url
}

output "service_url" {
  value = module.serverless_agent.service_url
}
```

### With Memorystore Redis for Session Storage

```hcl
module "serverless_api_redis" {
  source = "yaalalabs/ak-serverless/google"

  project_id           = "my-gcp-project"
  region               = "us-central1"
  product_alias        = "myapp"
  env_alias            = "prod"
  product_display_name = "Serverless API with Redis"
  
  module_name  = "chat"
  package_path = "${path.module}/dist"
  
  # Enable Memorystore Redis for session storage
  create_redis_cluster = true
  
  cpu    = "1"
  memory = "512Mi"
  
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
module "serverless_api_firestore" {
  source = "yaalalabs/ak-serverless/google"

  project_id           = "my-gcp-project"
  region               = "us-central1"
  product_alias        = "myapp"
  env_alias            = "prod"
  product_display_name = "Serverless API with Firestore"
  
  module_name  = "chat"
  package_path = "${path.module}/dist"
  
  # Enable Firestore for session storage (GCP equivalent of DynamoDB)
  create_firestore_database = true
  
  environment_variables = {
    ENVIRONMENT = "production"
    # Firestore connection details automatically injected:
    # AK_SESSION__FIRESTORE__DATABASE
    # AK_SESSION__FIRESTORE__PROJECT
  }
  
  api_version    = "v1"
  agent_endpoint = "chat"
}
```

### With Existing VPC

```hcl
module "serverless_api_vpc" {
  source = "yaalalabs/ak-serverless/google"

  project_id           = "my-gcp-project"
  region               = "us-central1"
  product_alias        = "myapp"
  env_alias            = "prod"
  product_display_name = "Serverless API with Existing VPC"
  
  module_name  = "api"
  package_path = "${path.module}/dist"
  
  # Use existing VPC instead of creating new one
  network_id        = "projects/my-project/global/networks/my-vpc"
  private_subnet_id = "projects/my-project/regions/us-central1/subnetworks/private-subnet"
  
  # Specify connector CIDR that doesn't overlap with existing subnets
  connector_cidr = "10.8.1.0/28"
  
  create_redis_cluster = true
  
  api_version    = "v1"
  agent_endpoint = "chat"
}
```

### Production Setup with High Availability

```hcl
module "production_api" {
  source = "yaalalabs/ak-serverless/google"

  project_id           = "enterprise-gcp-project"
  region               = "us-central1"
  product_alias        = "enterprise"
  env_alias            = "prod"
  product_display_name = "Enterprise Production API"
  
  module_name  = "core-api"
  package_path = "${path.module}/dist"
  is_production = true
  
  # Keep instances warm to eliminate cold starts
  min_instance_count = 2
  max_instance_count = 50
  
  # High performance configuration
  cpu    = "4"
  memory = "8Gi"
  timeout = 300
  backend_deadline = 300
  
  # Enable both Redis and Firestore
  create_redis_cluster      = true
  create_firestore_database = true
  
  # JWT Authorization
  authorizer = {
    issuer    = "https://accounts.google.com"
    jwks_uri  = "https://www.googleapis.com/oauth2/v3/certs"
    audiences = ["your-client-id.apps.googleusercontent.com"]
  }
  
  # Restrict direct Cloud Run access
  allow_unauthenticated_invocation = false
  
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

### Custom API Endpoints

```hcl
module "custom_endpoints_api" {
  source = "yaalalabs/ak-serverless/google"

  project_id    = "my-gcp-project"
  region        = "us-central1"
  product_alias = "myapp"
  env_alias     = "dev"
  
  module_name  = "api"
  package_path = "${path.module}/dist"
  
  api_version    = "v1"
  api_base_path  = "api"
  agent_endpoint = "chat"
  
  # Define custom API endpoints
  gateway_endpoints = [
    {
      path           = "health"
      method         = "GET"
      overwrite_path = "/health"
    },
    {
      path           = "custom"
      method         = "POST"
      overwrite_path = "/api/custom"
    },
    {
      path           = "status"
      method         = "GET"
      overwrite_path = "/status"
    }
  ]
  
  # Results in API endpoints:
  # GET  /api/v1/health  -> /health
  # POST /api/v1/custom  -> /api/custom
  # GET  /api/v1/status  -> /status
  # POST /api/v1/chat    -> /api/v1/chat (default)
  # POST /api/v1/chat-multipart -> /api/v1/chat-multipart (default)
}
```

### With MCP Server Support

```hcl
module "mcp_api" {
  source = "yaalalabs/ak-serverless/google"

  project_id    = "my-gcp-project"
  region        = "us-central1"
  product_alias = "myapp"
  env_alias     = "prod"
  
  module_name  = "mcp"
  package_path = "${path.module}/dist"
  
  # Enable MCP server endpoint
  enable_mcp_server = true
  
  api_version    = "v1"
  agent_endpoint = "chat"
  
  # This creates an additional endpoint:
  # ANY /api/v1/mcp -> /mcp/
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
| `min_instance_count` | Minimum instances (0 = scale to zero / serverless) | `number` | `0` | no |
| `max_instance_count` | Maximum number of instances | `number` | `10` | no |
| `container_port` | Port the container listens on | `number` | `8000` | no |
| `health_check_endpoint` | Health check path | `string` | `"/health"` | no |

**Key Feature**: `min_instance_count = 0` enables true serverless behavior (scale-to-zero). Set to 1+ to keep instances warm and eliminate cold starts.

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
| `connector_cidr` | CIDR block for VPC Access Connector. If null, auto-computed (e.g. '10.8.1.0/28') | `string` | `null` | no |
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
- `AK_SESSION__FIRESTORE__DATABASE`: Firestore database ID
- `AK_SESSION__FIRESTORE__PROJECT`: GCP project ID

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

### ⚡ Cloud Run Serverless

**True Scale-to-Zero**:
- **min_instance_count = 0**: No idle cost — pay only when requests are processed
- **Cold Starts**: First request after idle period experiences startup latency (~1-3 seconds)
- **Always-On Option**: Set `min_instance_count >= 1` to keep instances warm and eliminate cold starts

**Automatic Scaling**:
- Scales from 0 to `max_instance_count` based on request load
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
  - `AK_SESSION__FIRESTORE__DATABASE`
  - `AK_SESSION__FIRESTORE__PROJECT`

## 🏗️ Architecture

**Cloud Run Serverless with Scale-to-Zero**:

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
│  │         Serverless Container Instances                 │ │
│  │         • min_instance_count = 0 (scale to zero)       │ │
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
│  │    VPC Access Connector (10.8.0.0/28)                   │ │
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
- **Scale-to-Zero**: `min_instance_count = 0` means no instances run when idle (no cost)
- **Cold Starts**: First request after idle triggers container startup (~1-3 seconds)
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
      min_instance_count = 0  # Scale to zero
      max_instance_count = 5
      create_redis       = false
      create_firestore   = true
    }
    prod = {
      cpu                = "4"
      memory             = "8Gi"
      min_instance_count = 2  # Always warm
      max_instance_count = 50
      create_redis       = true
      create_firestore   = true
    }
  }
  env_config = local.config[var.env_alias]
}

module "api" {
  source = "yaalalabs/ak-serverless/google"
  
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

✅ Set `min_instance_count >= 1` to eliminate cold starts  
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

**Key Advantage**: With `min_instance_count = 0`, you pay **$0 when idle**!

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

| Configuration | Cloud Run | VPC Connector | Redis | Firestore | API Gateway | Total/Month |
|---------------|-----------|---------------|-------|-----------|-------------|-------------|
| Dev (scale-to-zero, Firestore) | $3 | $14 | $0 | ~$5 | $3 | ~$25 |
| Staging (1 warm instance, Redis) | $50 | $14 | $35 | $0 | $10 | ~$109 |
| Production (2+ warm, Redis HA) | $200 | $14 | $175 | $10 | $30 | ~$429 |

### Cost-Saving Tips

1. **Use Scale-to-Zero for Development**
   ```hcl
   min_instance_count = 0  # No idle cost
   ```

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
     ${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPOSITORY}/${IMAGE}:${TAG}
   ```

6. **Monitor and Optimize**
   - Use Cloud Monitoring to track request patterns
   - Adjust `max_instance_count` based on actual load
   - Enable request throttling to prevent cost spikes

### Cost Estimation Tool

```bash
# Calculate estimated monthly cost
REQUESTS_PER_MONTH=1000000
AVG_DURATION_MS=200
VCPU=1
MEMORY_GIB=0.5

CPU_COST=$(echo "$REQUESTS_PER_MONTH * ($AVG_DURATION_MS / 1000) * $VCPU * 0.000024" | bc -l)
MEMORY_COST=$(echo "$REQUESTS_PER_MONTH * ($AVG_DURATION_MS / 1000) * $MEMORY_GIB * 0.0000025" | bc -l)
REQUEST_COST=$(echo "$REQUESTS_PER_MONTH * 0.0000004" | bc -l)

TOTAL=$(echo "$CPU_COST + $MEMORY_COST + $REQUEST_COST" | bc -l)
echo "Estimated Cloud Run cost: \$$(printf '%.2f' $TOTAL)/month"
```

## 🔍 Troubleshooting

### Cloud Run Service Won't Start

**Issue**: Service fails to deploy or crashes on startup

**Solutions**:
1. Check Cloud Logging for errors:
   ```bash
   gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=${SERVICE_NAME}" \
     --limit 50 --format json
   ```

2. Verify Dockerfile builds locally:
   ```bash
   cd ${PACKAGE_PATH}
   docker build -t test-image .
   docker run -p 8000:8000 test-image
   ```

3. Check health check endpoint returns 200:
   ```bash
   curl http://localhost:8000/health
   ```

4. Verify environment variables are set correctly:
   ```bash
   gcloud run services describe ${SERVICE_NAME} \
     --region ${REGION} \
     --format="value(spec.template.spec.containers[0].env)"
   ```

### API Gateway Returns 404

**Issue**: API Gateway returns "Not Found" for valid endpoints

**Solutions**:
1. Verify OpenAPI spec was deployed:
   ```bash
   gcloud api-gateway api-configs describe ${CONFIG_ID} \
     --api=${API_ID} \
     --format=json
   ```

2. Check gateway_endpoints configuration matches your application routes

3. Ensure paths in OpenAPI spec match Cloud Run service paths

4. Test Cloud Run service directly (bypass API Gateway):
   ```bash
   curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
     ${SERVICE_URL}/api/v1/chat
   ```

### Cannot Connect to Redis/Firestore

**Issue**: Cloud Run service cannot reach Redis or Firestore

**Solutions**:
1. Verify VPC Connector is active:
   ```bash
   gcloud compute networks vpc-access connectors describe ${CONNECTOR_NAME} \
     --region ${REGION}
   ```

2. Check firewall rules allow traffic from connector:
   ```bash
   gcloud compute firewall-rules list \
     --filter="name~${FIREWALL_NAME}"
   ```

3. Verify environment variables are injected:
   ```bash
   # For Redis
   gcloud run services describe ${SERVICE_NAME} \
     --region ${REGION} \
     --format="value(spec.template.spec.containers[0].env[?(@.name=='AK_SESSION__REDIS__URL')].value)"
   
   # For Firestore
   gcloud run services describe ${SERVICE_NAME} \
     --region ${REGION} \
     --format="value(spec.template.spec.containers[0].env[?(@.name=='AK_SESSION__FIRESTORE__DATABASE')].value)"
   ```

4. Test connectivity from Cloud Run:
   ```python
   # Add to your application for debugging
   import socket
   redis_host = "10.0.2.3"  # Your Redis private IP
   try:
       socket.create_connection((redis_host, 6379), timeout=5)
       print("Redis connection successful")
   except Exception as e:
       print(f"Redis connection failed: {e}")
   ```

### Cold Start Latency

**Issue**: First request after idle period is slow

**Solutions**:
1. **Keep instances warm** (eliminates cold starts):
   ```hcl
   min_instance_count = 1  # or higher
   ```

2. **Optimize Docker image**:
   - Use smaller base images (alpine, slim)
   - Minimize layers
   - Cache dependencies

3. **Reduce startup time**:
   - Lazy-load heavy dependencies
   - Use startup CPU boost (automatic in Cloud Run)
   - Optimize application initialization

4. **Monitor cold start metrics**:
   ```bash
   gcloud logging read "resource.type=cloud_run_revision \
     AND jsonPayload.message=~'Cold start'" \
     --limit 10
   ```

### Permission Denied Errors

**Issue**: Service account lacks required permissions

**Solutions**:
1. Check Service Account IAM roles:
   ```bash
   gcloud projects get-iam-policy ${PROJECT_ID} \
     --flatten="bindings[].members" \
     --filter="bindings.members:serviceAccount:${SERVICE_ACCOUNT_EMAIL}"
   ```

2. Grant required roles:
   ```bash
   # For Redis access
   gcloud projects add-iam-policy-binding ${PROJECT_ID} \
     --member="serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
     --role="roles/redis.editor"
   
   # For Firestore access
   gcloud projects add-iam-policy-binding ${PROJECT_ID} \
     --member="serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
     --role="roles/datastore.user"
   ```

3. Verify Cloud Run invocation permissions:
   ```bash
   gcloud run services get-iam-policy ${SERVICE_NAME} \
     --region ${REGION}
   ```

### VPC Connector CIDR Conflicts

**Issue**: Connector CIDR overlaps with existing subnets

**Solutions**:
1. Manually specify non-overlapping CIDR:
   ```hcl
   connector_cidr = "10.8.1.0/28"  # Must be /28
   ```

2. List existing subnet CIDRs:
   ```bash
   gcloud compute networks subnets list \
     --network=${NETWORK_NAME} \
     --format="table(name,ipCidrRange)"
   ```

3. Choose CIDR from available ranges:
   - 10.8.0.0/28 through 10.8.255.240/28 (256 possible /28 subnets)
   - Must not overlap with any existing subnet

### API Gateway JWT Authorization Fails

**Issue**: Valid JWT tokens are rejected

**Solutions**:
1. Verify authorizer configuration:
   ```hcl
   authorizer = {
     issuer    = "https://accounts.google.com"  # Must match JWT iss claim
     jwks_uri  = "https://www.googleapis.com/oauth2/v3/certs"
     audiences = ["your-client-id.apps.googleusercontent.com"]  # Must match JWT aud claim
   }
   ```

2. Test JWT token:
   ```bash
   # Decode JWT to verify claims
   echo ${JWT_TOKEN} | cut -d'.' -f2 | base64 -d | jq
   ```

3. Check API Gateway logs:
   ```bash
   gcloud logging read "resource.type=api AND resource.labels.service=${GATEWAY_ID}" \
     --limit 20
   ```

## 📊 Monitoring and Observability

### Cloud Logging Integration

**Automatic Logging**:
- Cloud Run automatically sends logs to Cloud Logging
- No additional configuration required
- Logs include request/response, errors, and custom application logs

**View Logs**:
```bash
# View recent logs
gcloud logging read "resource.type=cloud_run_revision \
  AND resource.labels.service_name=${SERVICE_NAME}" \
  --limit 50 --format json

# Follow logs in real-time
gcloud logging tail "resource.type=cloud_run_revision \
  AND resource.labels.service_name=${SERVICE_NAME}"

# Filter by severity
gcloud logging read "resource.type=cloud_run_revision \
  AND resource.labels.service_name=${SERVICE_NAME} \
  AND severity>=ERROR" \
  --limit 20
```

### Key Metrics to Monitor

**Cloud Run Metrics**:
- **Request Count**: Number of requests per second
- **Request Latency**: P50, P95, P99 latencies
- **Instance Count**: Active instances (should be 0 when idle if min=0)
- **CPU Utilization**: Percentage of allocated CPU used
- **Memory Utilization**: Percentage of allocated memory used
- **Container Startup Latency**: Cold start duration

**API Gateway Metrics**:
- **Request Count**: Requests through API Gateway
- **Error Rate**: 4xx and 5xx responses
- **Latency**: End-to-end request latency
- **Quota Usage**: Throttling quota consumption (if enabled)

**State Management Metrics**:
- **Redis**: Connection count, memory usage, operations/sec
- **Firestore**: Read/write operations, document count

### Cloud Monitoring Queries

```bash
# Cloud Run request count
gcloud monitoring time-series list \
  --filter='metric.type="run.googleapis.com/request_count" AND resource.labels.service_name="${SERVICE_NAME}"' \
  --format=json

# Cloud Run latencies
gcloud monitoring time-series list \
  --filter='metric.type="run.googleapis.com/request_latencies" AND resource.labels.service_name="${SERVICE_NAME}"' \
  --format=json

# API Gateway request count
gcloud monitoring time-series list \
  --filter='metric.type="serviceruntime.googleapis.com/api/request_count" AND resource.labels.service="${GATEWAY_ID}"' \
  --format=json
```

### Custom Metrics

```python
# Python example using OpenTelemetry
from opentelemetry import metrics
from opentelemetry.exporter.cloud_monitoring import CloudMonitoringMetricsExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader

# Configure Cloud Monitoring exporter
exporter = CloudMonitoringMetricsExporter()
reader = PeriodicExportingMetricReader(exporter)
provider = MeterProvider(metric_readers=[reader])
metrics.set_meter_provider(provider)

# Create custom metrics
meter = metrics.get_meter(__name__)
request_counter = meter.create_counter(
    "custom.requests",
    description="Number of requests processed",
)

# Increment counter
request_counter.add(1, {"endpoint": "/chat", "status": "success"})
```

### Alerting

**Create Alert Policy**:
```bash
# Alert on high error rate
gcloud alpha monitoring policies create \
  --notification-channels=${CHANNEL_ID} \
  --display-name="High Error Rate" \
  --condition-display-name="Error rate > 5%" \
  --condition-threshold-value=0.05 \
  --condition-threshold-duration=300s \
  --condition-filter='resource.type="cloud_run_revision" AND metric.type="run.googleapis.com/request_count" AND metric.labels.response_code_class="5xx"'

# Alert on high latency
gcloud alpha monitoring policies create \
  --notification-channels=${CHANNEL_ID} \
  --display-name="High Latency" \
  --condition-display-name="P95 latency > 1s" \
  --condition-threshold-value=1000 \
  --condition-threshold-duration=300s \
  --condition-filter='resource.type="cloud_run_revision" AND metric.type="run.googleapis.com/request_latencies" AND metric.labels.percentile="95"'
```

### Distributed Tracing

**Enable Cloud Trace**:
```python
# Python example
from opentelemetry import trace
from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

# Configure Cloud Trace exporter
trace.set_tracer_provider(TracerProvider())
tracer = trace.get_tracer(__name__)
span_exporter = CloudTraceSpanExporter()
span_processor = BatchSpanProcessor(span_exporter)
trace.get_tracer_provider().add_span_processor(span_processor)

# Create spans
with tracer.start_as_current_span("process_request"):
    # Your code here
    with tracer.start_as_current_span("database_query"):
        # Database operation
        pass
```

### Log-Based Metrics

```bash
# Create log-based metric for custom events
gcloud logging metrics create custom_event_count \
  --description="Count of custom events" \
  --log-filter='resource.type="cloud_run_revision" AND jsonPayload.event="custom_event"'

# Query log-based metric
gcloud monitoring time-series list \
  --filter='metric.type="logging.googleapis.com/user/custom_event_count"' \
  --format=json
```

## 🔄 Cross-Cloud Comparison

### Service Equivalents

| Feature | AWS | Azure | GCP |
|---------|-----|-------|-----|
| **Serverless Compute** | Lambda | Azure Functions | Cloud Run (min_instance=0) |
| **Container Platform** | ECS Fargate | Container Apps | Cloud Run (min_instance≥1) |
| **API Gateway** | API Gateway | API Management | API Gateway (ESPv2) |
| **Session Storage (NoSQL)** | DynamoDB | Cosmos DB | Firestore |
| **Session Storage (Cache)** | ElastiCache Redis | Azure Cache for Redis | Memorystore for Redis |
| **Container Registry** | ECR | ACR | Artifact Registry |
| **VPC** | VPC | VNet | VPC Network |
| **Private Connectivity** | Security Groups | NSG | VPC Connector + Firewall Rules |
| **Identity** | IAM Role | Managed Identity | Service Account |
| **Logging** | CloudWatch Logs | Application Insights | Cloud Logging |
| **Monitoring** | CloudWatch Metrics | Azure Monitor | Cloud Monitoring |
| **Tracing** | X-Ray | Application Insights | Cloud Trace |

### Key Differences

#### Scale-to-Zero Behavior

| Cloud | Service | Scale-to-Zero | Cold Start | Always-On Option |
|-------|---------|---------------|------------|------------------|
| **AWS** | Lambda | ✅ Always | Yes (~1-3s) | ❌ (use Fargate) |
| **Azure** | Functions | ✅ Consumption plan | Yes (~1-3s) | ✅ Premium plan |
| **GCP** | Cloud Run | ✅ min_instance=0 | Yes (~1-3s) | ✅ min_instance≥1 |

**GCP Advantage**: Single service (Cloud Run) supports both serverless and always-on modes via `min_instance_count` parameter.

#### API Gateway Features

| Feature | AWS API Gateway | Azure APIM | GCP API Gateway |
|---------|-----------------|------------|-----------------|
| **Specification** | OpenAPI 3.0 | OpenAPI 3.0 | OpenAPI 2.0 (Swagger) |
| **Native CORS** | ✅ Yes | ✅ Yes | ❌ No (app must handle) |
| **JWT Authorization** | Lambda Authorizer | JWT validation | ✅ Native JWT validation |
| **Throttling** | ✅ Native | ✅ Native | ✅ Quota-based |
| **WebSocket** | ✅ Yes | ❌ No | ❌ No |
| **Request Transformation** | ✅ VTL templates | ✅ Policies | ❌ Limited |

#### Pricing Comparison (1M requests, 200ms, 512Mi)

| Cloud | Compute | API Gateway | Total |
|-------|---------|-------------|-------|
| **AWS Lambda** | ~$3.50 | ~$3.50 | ~$7.00 |
| **Azure Functions** | ~$6.60 | ~$3.50 | ~$10.10 |
| **GCP Cloud Run** | ~$3.05 | ~$3.00 | ~$6.05 |

**Note**: GCP is most cost-effective for serverless workloads, especially with scale-to-zero.

#### State Management Comparison

| Feature | AWS | Azure | GCP |
|---------|-----|-------|-----|
| **NoSQL Database** | DynamoDB | Cosmos DB | Firestore |
| **Pricing Model** | Pay per request | Pay per RU | Pay per operation |
| **Free Tier** | 25 GB, 25 RCU/WCU | 1000 RU/s, 25 GB | 1 GB storage, 50K reads/day |
| **Cache Service** | ElastiCache Redis | Azure Cache for Redis | Memorystore for Redis |
| **Cache Pricing** | ~$15/month (1GB) | ~$16/month (1GB) | ~$35/month (1GB) |

### Migration Considerations

#### From AWS Lambda to GCP Cloud Run

**Similarities**:
- Both support scale-to-zero
- Both use container images
- Both integrate with API Gateway

**Differences**:
- **Packaging**: Lambda uses ZIP or container; Cloud Run always uses containers
- **Timeout**: Lambda max 15 minutes; Cloud Run max 60 minutes
- **Memory**: Lambda 128MB-10GB; Cloud Run 128Mi-32Gi
- **Cold Starts**: Similar (~1-3 seconds)

**Migration Steps**:
1. Containerize Lambda function (if using ZIP)
2. Update environment variable names
3. Replace DynamoDB with Firestore or ElastiCache with Memorystore
4. Update API Gateway configuration (OpenAPI 2.0 vs 3.0)
5. Update IAM roles to Service Account

#### From Azure Functions to GCP Cloud Run

**Similarities**:
- Both support scale-to-zero and always-on
- Both use container-based deployment
- Both integrate with API Management/Gateway

**Differences**:
- **Configuration**: Azure uses host.json; GCP uses Terraform variables
- **Bindings**: Azure has input/output bindings; GCP uses standard HTTP
- **Networking**: Azure uses VNet integration; GCP uses VPC Connector

**Migration Steps**:
1. Convert Azure Functions to standard HTTP handlers
2. Remove Azure-specific bindings
3. Replace Cosmos DB with Firestore or Azure Cache with Memorystore
4. Update APIM policies to API Gateway OpenAPI spec
5. Update Managed Identity to Service Account

## 📚 Additional Resources

### GCP Documentation

- [Cloud Run Documentation](https://cloud.google.com/run/docs) - Official Cloud Run documentation
- [API Gateway Documentation](https://cloud.google.com/api-gateway/docs) - API Gateway setup and configuration
- [Memorystore for Redis](https://cloud.google.com/memorystore/docs/redis) - Managed Redis service
- [Firestore Documentation](https://cloud.google.com/firestore/docs) - NoSQL document database
- [VPC Documentation](https://cloud.google.com/vpc/docs) - Virtual Private Cloud networking
- [Serverless VPC Access](https://cloud.google.com/vpc/docs/configure-serverless-vpc-access) - VPC Connector setup
- [Cloud Logging](https://cloud.google.com/logging/docs) - Logging and log analysis
- [Cloud Monitoring](https://cloud.google.com/monitoring/docs) - Metrics and monitoring

### Pricing and Cost Management

- [Cloud Run Pricing](https://cloud.google.com/run/pricing) - Detailed pricing information
- [API Gateway Pricing](https://cloud.google.com/api-gateway/pricing) - API Gateway costs
- [Memorystore Pricing](https://cloud.google.com/memorystore/pricing) - Redis pricing tiers
- [Firestore Pricing](https://cloud.google.com/firestore/pricing) - NoSQL database costs
- [GCP Pricing Calculator](https://cloud.google.com/products/calculator) - Estimate total costs

### Best Practices and Guides

- [Cloud Run Best Practices](https://cloud.google.com/run/docs/best-practices) - Performance and optimization
- [Container Image Optimization](https://cloud.google.com/run/docs/tips/general) - Reduce cold starts
- [Security Best Practices](https://cloud.google.com/run/docs/securing/overview) - Secure your services
- [Troubleshooting Guide](https://cloud.google.com/run/docs/troubleshooting) - Common issues and solutions

### Terraform Resources

- [Google Provider Documentation](https://registry.terraform.io/providers/hashicorp/google/latest/docs) - Terraform GCP provider
- [Cloud Run Resource](https://registry.terraform.io/providers/hashicorp/google/latest/docs/resources/cloud_run_v2_service) - Cloud Run Terraform resource
- [API Gateway Resources](https://registry.terraform.io/providers/hashicorp/google-beta/latest/docs/resources/api_gateway_api) - API Gateway Terraform resources

### Community and Support

- [GCP Community](https://www.googlecloudcommunity.com/) - Community forums and discussions
- [Stack Overflow](https://stackoverflow.com/questions/tagged/google-cloud-run) - Q&A for Cloud Run
- [GitHub Issues](https://github.com/googleapis/google-cloud-go/issues) - Report issues with GCP SDKs

## 🔗 Related Modules

### Agent Kernel Modules

- [GCP Common Module](../common/) - Shared infrastructure modules for GCP deployments
- [GCP Containerized Module](../containerized/) - Always-on Cloud Run deployment (min_instance≥1)
- [Artifact Registry Module](../common/modules/artifact-registry/) - Container image management
- [VPC Module](../common/modules/vpc/) - Virtual Private Cloud networking
- [Memorystore Module](../common/modules/memorystore/) - Managed Redis clusters
- [Firestore Module](../common/modules/firestore/) - NoSQL database setup

### Cross-Cloud Modules

- [AWS Serverless Module](../../ak-aws/serverless/) - AWS Lambda deployment
- [Azure Serverless Module](../../ak-azure/serverless/) - Azure Functions deployment

### Example Applications

- [GCP Serverless OpenAI Example](../../../examples/gcp-serverless/openai/) - Multi-agent OpenAI deployment with Redis
- [GCP Serverless Firestore Example](../../../examples/gcp-serverless/openai-firestore/) - OpenAI deployment with Firestore
- [GCP Containerized Example](../../../examples/gcp-containerized/openai/) - Always-on deployment with custom routes

---

**Note**: This module automatically creates VPC networks, subnets, VPC Connectors, firewall rules, and IAM bindings. Ensure your GCP credentials have sufficient permissions to create these resources. The Service Account used by Cloud Run is granted the minimum required IAM roles for accessing Redis and Firestore.

## License

Unless otherwise specified, all content, including all source code files and documentation files in this repository are:

Copyright (c) 2025-2026 Yaala Labs.

Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with the License. You may obtain a copy of the License at

http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the License for the specific language governing permissions and limitations under the License.
