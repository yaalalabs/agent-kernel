# Agent Kernel - Azure Containerized Module

A comprehensive Terraform module for deploying containerized applications on Azure using Container Apps, with API Management (APIM), and optional Redis or Cosmos DB integration.

## 📋 Overview

This module provides a complete containerized deployment solution on Azure:

- 🐳 **Azure Container Apps**: Serverless container orchestration with auto-scaling in a single environment
- 🌐 **API Management (APIM)**: Developer SKU API gateway with routing, policies, and monitoring
- 🔒 **VNet Integration**: Private networking with specialized subnets for functions and infrastructure
- 💾 **State Management**: Optional Azure Managed Redis or Cosmos DB Table API for session/state persistence
- 📊 **Application Insights**: Container logs, metrics, and distributed tracing
- 🏗️ **Automated Build**: Docker image building and ACR management with private endpoints

Perfect for microservices, web applications, APIs requiring persistent connections, and applications needing API management capabilities.

## 📋 Requirements

| Name | Version |
|------|---------|
| Terraform | >= 1.9.5 |
| Azure Provider | >= 4.57.0 |
| Docker Provider | 3.6.2 |

## 🚀 Usage

### Basic Containerized API

```hcl
module "container_app" {
  source = "yaalalabs/ak-containerized/azurerm"

  region               = "centralus"
  resource_group_name  = "myapp-prod-rg"
  product_alias        = "myapp"
  env_alias            = "prod"
  product_display_name = "My Containerized App"
  
  module_name     = "api"
  package_path    = "${path.module}/src"  # Directory with Dockerfile
  publisher_email = "admin@mycompany.com"
  
  # Container Configuration
  container_min_replicas = 1
  container_max_replicas = 5
  container_port         = 8000
  
  # Health check
  container_health_check_path = "/health"
  
  # Environment variables
  environment_variables = {
    ENVIRONMENT = "production"
    LOG_LEVEL   = "info"
    PORT        = "8000"
  }
  
  # API Configuration
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
    Environment = "production"
    Service     = "api"
  }
}

output "api_url" {
  value = module.container_app.api_base_url
}

output "container_app_fqdn" {
  value = module.container_app.container_app_fqdn
}
```

### With Redis and Custom VNet

```hcl
module "container_app_redis" {
  source = "yaalalabs/ak-containerized/azurerm"

  region               = "centralus"
  resource_group_name  = "myapp-prod-rg"
  product_alias        = "myapp"
  env_alias            = "prod"
  product_display_name = "Stateful API"
  
  module_name     = "stateful-api"
  package_path    = "${path.module}/app"
  publisher_email = "admin@mycompany.com"
  
  # Create new VNet with custom CIDR
  vnet_cidr             = "10.1.0.0/16"
  public_subnet_cidrs   = ["10.1.1.0/24", "10.1.2.0/24"]
  private_subnet_cidrs  = ["10.1.10.0/23", "10.1.12.0/23"]
  
  # Enable Redis Enterprise
  create_redis_cluster = true
  is_production       = true  # Uses Balanced_B5 SKU
  
  # Container Configuration
  container_min_replicas = 2
  container_max_replicas = 8
  container_port         = 3000
  
  environment_variables = {
    NODE_ENV = "production"
    WORKERS  = "4"
    # Redis URL automatically injected as AK_SESSION__REDIS__URL
  }
  
  api_version    = "v1"
  agent_endpoint = "session"
}
```

### With Cosmos DB for Session Storage

```hcl
module "container_app_cosmosdb" {
  source = "yaalalabs/ak-containerized/azurerm"

  region               = "centralus"
  resource_group_name  = "myapp-prod-rg"
  product_alias        = "myapp"
  env_alias            = "prod"
  product_display_name = "Serverless State API"
  
  module_name     = "serverless-api"
  package_path    = "${path.module}/app"
  publisher_email = "admin@mycompany.com"
  
  # Enable Cosmos DB Table API for session storage
  create_cosmosdb_cluster                    = true
  cosmosdb_consistency_level                 = "Session"
  cosmosdb_public_network_access_enabled     = false
  cosmosdb_point_in_time_recovery_enabled    = true
  cosmosdb_server_side_encryption_enabled    = true
  
  # Container Configuration
  container_min_replicas = 1
  container_max_replicas = 6
  container_port         = 8000
  
  environment_variables = {
    # Cosmos DB connection details automatically injected:
    # AK_SESSION__COSMOSDB__TABLE_NAME
    # AK_SESSION__COSMOSDB__TABLE_ENDPOINT
    # AK_SESSION__COSMOSDB__CONNECTION_STRING (as secret)
  }
  
  api_version    = "v1"
  agent_endpoint = "chat"
}
```

## 📥 Inputs

### Core Configuration

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|:--------:|
| `region` | Azure region for deployment | `string` | n/a | yes |
| `resource_group_name` | Name of the Azure resource group | `string` | n/a | yes |
| `product_alias` | Short identifier for the product | `string` | n/a | yes |
| `env_alias` | Environment identifier (dev, staging, prod) | `string` | n/a | yes |
| `product_display_name` | Human-readable product name | `string` | `"An Agent Kernel deployment"` | no |
| `module_name` | Module name for resource identification | `string` | n/a | yes |
| `package_path` | Path to Docker source directory (with Dockerfile) | `string` | n/a | yes |
| `environment_variables` | Environment variables for container | `map(string)` | `{}` | no |
| `tags` | Additional tags for resources | `map(string)` | `{}` | no |

### API Management Configuration

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|:--------:|
| `api_version` | API version for endpoint path | `string` | `"v1"` | no |
| `agent_endpoint` | API endpoint name | `string` | `"chat"` | no |
| `api_base_path` | Base path segment for API (e.g., 'api') | `string` | `"api"` | no |
| `publisher_name` | API Management publisher name | `string` | `"Agent Kernel"` | no |
| `publisher_email` | API Management publisher email | `string` | n/a | yes |
| `gateway_endpoints` | List of custom HTTP API endpoints | `list(object)` | `[]` | no |

### Container Configuration

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|:--------:|
| `container_min_replicas` | Minimum number of container replicas (0-300) | `number` | `1` | no |
| `container_max_replicas` | Maximum number of container replicas (1-300) | `number` | `10` | no |
| `container_port` | Container port exposed by application | `number` | `8000` | no |
| `container_health_check_path` | Health check path for probes | `string` | `"/health"` | no |
| `container_scale_concurrent_requests` | Concurrent requests to trigger scaling | `number` | `10` | no |

### State Management Configuration

#### Redis Configuration
| Name | Description | Type | Default | Required |
|------|-------------|------|---------|:--------:|
| `create_redis_cluster` | Enable Azure Managed Redis Enterprise | `bool` | `false` | no |
| `is_production` | Production environment flag (affects Redis SKU) | `bool` | `false` | no |

**Redis Environment Variables (Auto-injected when enabled)**:
- `AK_SESSION__REDIS__URL`: Complete Redis connection URL with authentication

#### Cosmos DB Configuration
| Name | Description | Type | Default | Required |
|------|-------------|------|---------|:--------:|
| `create_cosmosdb_cluster` | Enable Cosmos DB Table API | `bool` | `false` | no |
| `cosmosdb_consistency_level` | Cosmos DB consistency level | `string` | `"Session"` | no |
| `cosmosdb_public_network_access_enabled` | Enable public access for Cosmos DB | `bool` | `false` | no |
| `cosmosdb_point_in_time_recovery_enabled` | Enable PITR for Cosmos DB | `bool` | `false` | no |
| `cosmosdb_server_side_encryption_enabled` | Enable encryption for Cosmos DB | `bool` | `true` | no |
| `cosmosdb_key_vault_key_id` | Key Vault key ID for Cosmos DB encryption | `string` | `null` | no |

**Cosmos DB Environment Variables (Auto-injected when enabled)**:
- `AK_SESSION__COSMOSDB__TABLE_NAME`: Table name (`session_store`)
- `AK_SESSION__COSMOSDB__TABLE_ENDPOINT`: Table API endpoint URL
- `AK_SESSION__COSMOSDB__CONNECTION_STRING`: Connection string (stored as secret)

## 📤 Outputs

| Name | Description | Example |
|------|-------------|---------|
| `container_app_fqdn` | FQDN of the Container App | `myapp-prod-api-app.proudpond-12345678.eastus.azurecontainerapps.io` |
| `api_management_gateway_url` | APIM Gateway URL | `https://myapp-prod-apim.azure-api.net` |
| `api_base_url` | Complete API base URL | `https://myapp-prod-apim.azure-api.net/api/v1` |
| `container_app_environment_id` | Container App Environment ID | `/subscriptions/.../containerAppEnvironments/myapp-prod-api-env` |
| `log_analytics_workspace_id` | Log Analytics Workspace ID | `/subscriptions/.../workspaces/myapp-prod-api-logs` |
| `application_insights_connection_string` | Application Insights connection string (sensitive) | `InstrumentationKey=...` |
| `container_registry_login_server` | ACR login server | `myappprodreg123abc.azurecr.io` |
| `vnet_id` | VNet ID (created or used) | `/subscriptions/.../virtualNetworks/myapp-prod-vnet` |
| `redis_url` | Redis connection URL (if enabled, sensitive) | `rediss://:password@hostname:10000` |
| `cosmosdb_table_name` | Cosmos DB table name (if enabled) | `myapp-prod-api-session_store` |
| `cosmosdb_endpoint` | Cosmos DB endpoint (if enabled, sensitive) | `https://myapp-prod-api-cosmos.table.cosmos.azure.com` |

## ✨ Features

### 🐳 Azure Container Apps Configuration

**Single Container App Environment**:
- One Container App Environment hosts one Container App
- Serverless container orchestration with auto-scaling
- Internal load balancer enabled for secure access via APIM
- Automatic CPU/Memory allocation based on `is_production` flag:
  - **Development**: 0.5 vCPU, 1 GB memory
  - **Production**: 1.0 vCPU, 2 GB memory

**Health Probes**:
- **Startup Probe**: Initial health check during container startup
- **Liveness Probe**: Ongoing health monitoring (restarts unhealthy containers)
- **Readiness Probe**: Traffic routing decisions

**Auto-scaling**:
- HTTP-based scaling using concurrent request metrics
- Scale-to-zero capability (set `container_min_replicas = 0`)
- Configurable min/max replica counts (0-300)

### 🌐 API Management (APIM) Integration

**Developer SKU Features**:
- Cost-effective tier suitable for development and testing
- External VNet integration for secure communication
- No SLA guarantees (suitable for non-production)
- Single deployment unit

**API Gateway Architecture**:
```
https://{apim-name}.azure-api.net/{api_base_path}/{version}/{endpoint}
```

**Default Endpoints**:
- `POST /{api_base_path}/{version}/{agent_endpoint}` → `/run`
- `POST /{api_base_path}/{version}/{agent_endpoint}-multipart` → `/run-multipart`

**Private DNS Integration**:
- Automatic DNS zone creation for Container App domain
- DNS A records for Container App resolution
- Wildcard DNS records for revision support

### 🔒 Network Security

**VNet Architecture**:
- **Infrastructure Subnet**: APIM and private endpoints
- **Function Subnet**: Container App Environment with delegation
- **NSG Rules**: Configured for APIM requirements and VNet communication

**Security Features**:
- Internal load balancer (no direct internet access to containers)
- Private endpoints for all data services
- System-assigned managed identity for Container App
- Secrets management for sensitive configuration

## 🏗️ Architecture

**Single Container App Environment Architecture**:

```
                        ┌─────────────────────┐
                        │   Internet          │
                        └──────────┬──────────┘
                                   │ HTTPS
                                   ▼
┌──────────────────────────────────────────────────────────────┐
│                       VNet                                   │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐ │
│  │              Infrastructure Subnet                     │ │
│  │                                                        │ │
│  │  ┌─────────────────────┐  ┌─────────────────────────┐ │ │
│  │  │   API Management    │  │   Private Endpoints     │ │ │
│  │  │   (Developer SKU)   │  │   • Redis Enterprise    │ │ │
│  │  │   External VNet     │  │   • Cosmos DB           │ │ │
│  │  └──────────┬──────────┘  │   • Container Registry  │ │ │
│  │             │             └─────────────────────────┘ │ │
│  │             │ Private DNS                            │ │
│  │             │ Resolution                             │ │
│  └─────────────┼────────────────────────────────────────┘ │
│                │                                          │
│  ┌─────────────┼────────────────────────────────────────┐ │
│  │             │        Function Subnet                 │ │
│  │             ▼                                        │ │
│  │  ┌─────────────────────────────────────────────────┐ │ │
│  │  │     Single Container App Environment           │ │ │
│  │  │     (Internal Load Balancer Enabled)           │ │ │
│  │  │                                                │ │ │
│  │  │  ┌─────────────────────────────────────────┐  │ │ │
│  │  │  │        Container App                    │  │ │ │
│  │  │  │  • Auto-scaling (min/max replicas)     │  │ │ │
│  │  │  │  • Health probes (startup/live/ready)  │  │ │ │
│  │  │  │  • Environment variables & secrets     │  │ │ │
│  │  │  │  • ACR integration                     │  │ │ │
│  │  │  └─────────────────────────────────────────┘  │ │ │
│  │  └─────────────────────────────────────────────────┘ │ │
│  └───────────────────────────────────────────────────────┘ │
│                                                              │
│  ┌───────────────────────────────────────────────────────┐  │
│  │                Public Subnets                         │  │
│  │          ┌────────────────────────┐                   │  │
│  │          │   NAT Gateway          │                   │  │
│  │          │   (Outbound Internet)  │                   │  │
│  │          └────────────────────────┘                   │  │
│  └───────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
```

**Key Architecture Points**:
- **Single Container App Environment**: One environment hosts one Container App (not multiple apps)
- **APIM Developer SKU**: Cost-effective tier suitable for development and testing
- **Internal Load Balancer**: Container App uses internal LB, accessed via APIM
- **Function Subnet**: Container App Environment deployed in the function subnet (subnet 2)
- **Infrastructure Subnet**: APIM and private endpoints in infrastructure subnet (subnet 1)

## 🎯 Application Configuration

### Environment Variables vs config.yaml

**Environment Variables** (recommended for simple configurations):
```hcl
environment_variables = {
  LOG_LEVEL     = "info"
  DATABASE_URL  = "postgresql://..."
  REDIS_ENABLED = "true"
  # Auto-injected variables:
  # AK_SESSION__REDIS__URL (if Redis enabled)
  # AK_SESSION__COSMOSDB__TABLE_NAME (if Cosmos DB enabled)
  # AK_SESSION__COSMOSDB__TABLE_ENDPOINT (if Cosmos DB enabled)
  # APPLICATIONINSIGHTS_CONNECTION_STRING (always injected)
}
```

**config.yaml file** (for complex configurations):
Place `config.yaml` in your `package_path` directory. The file will be included in the Docker image build.

```yaml
# config.yaml in your package_path
app:
  name: "my-agent"
  version: "1.0.0"
  
logging:
  level: "info"
  format: "json"
  
session:
  provider: "redis"  # or "cosmosdb"
  ttl: 3600
  
features:
  multipart_upload: true
  streaming: false
```

### Health Check Implementation

```dockerfile
# In your Dockerfile
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1
```

```python
# In your application
@app.get("/health")
async def health_check():
    # Check dependencies
    redis_ok = await check_redis_connection() if os.getenv('AK_SESSION__REDIS__URL') else True
    cosmos_ok = await check_cosmos_connection() if os.getenv('AK_SESSION__COSMOSDB__TABLE_NAME') else True
    
    return {
        "status": "healthy" if redis_ok and cosmos_ok else "unhealthy",
        "timestamp": time.time(),
        "dependencies": {
            "redis": "ok" if redis_ok else "error",
            "cosmos": "ok" if cosmos_ok else "error"
        }
    }
```

## 🔍 Troubleshooting

### Container Won't Start

**Issue**: Container Apps fail to start or restart frequently

**Solutions**:
1. Check Application Insights logs
2. Verify health check endpoint returns 200 OK
3. Check environment variables and secrets are properly configured
4. Verify Docker image builds and runs locally

### APIM Cannot Reach Container App

**Issue**: API Management returns 502/503 errors

**Solutions**:
1. Verify private DNS resolution for Container App domain
2. Check NSG rules allow APIM → Container App traffic
3. Verify Container App is running and healthy
4. Check APIM backend configuration

### Redis/Cosmos DB Connection Issues

**Solutions**:
- Verify environment variables are properly injected
- Check private endpoint connectivity
- Ensure secrets are correctly configured
- Test connections from within the Container App
- Check the NSG rules betweenn the application subnet and the infrastructure subnet

## 📚 Additional Resources

- [Azure Container Apps Documentation](https://docs.microsoft.com/en-us/azure/container-apps/)
- [API Management Documentation](https://docs.microsoft.com/en-us/azure/api-management/)
- [Azure Managed Redis Documentation](https://docs.microsoft.com/en-us/azure/azure-cache-for-redis/)
- [Cosmos DB Table API Documentation](https://docs.microsoft.com/en-us/azure/cosmos-db/table/)

## 🔗 Related Modules

- [ACR Module](../common/modules/acr/) - For building and storing Docker images
- [VNet Module](../common/modules/vnet/) - For custom VNet configurations
- [Redis Module](../common/modules/redis/) - For standalone Redis clusters
- [Cosmos Module](../common/modules/cosmos/) - For standalone Cosmos DB instances

---

**Note**: This module creates a single Container App Environment hosting one Container App. The APIM Developer SKU provides cost-effective API management suitable for development and testing scenarios. For production workloads requiring SLA guarantees, consider upgrading to higher APIM tiers.

## License

Unless otherwise specified, all content, including all source code files and documentation files in this repository are:

Copyright (c) 2025-2026 Yaala Labs.

Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with the License. You may obtain a copy of the License at

http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the License for the specific language governing permissions and limitations under the License.