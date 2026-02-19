# Agent Kernel - Azure Serverless Module

A comprehensive Terraform module for deploying serverless applications on Azure using Azure Functions Flex Consumption plan, with API Management (APIM), and optional Redis or Cosmos DB integration.

## 📋 Overview

This module provides a complete serverless deployment solution on Azure:

- ⚡ **Azure Functions Flex Consumption**: Next-generation serverless compute with VNet integration
- 🌐 **API Management (APIM)**: Consumption/Basic tier API gateway with routing and policies
- 🔄 **Flexible Deployment**: Support for ZIP packages and container images
- 🔒 **VNet Integration**: Private networking with specialized subnet delegation
- 💾 **State Management**: Optional Azure Managed Redis or Cosmos DB Table API for session/state persistence
- 📊 **Application Insights**: Function logs, metrics, and distributed tracing
- 🏗️ **Automated Deployment**: ZIP package upload and function code deployment

Perfect for microservices, API backends, event-driven architectures, and serverless web applications requiring REST endpoints with enterprise API management.

## 📋 Requirements

| Name | Version |
|------|---------|
| Terraform | >= 1.9.5 |
| Azure Provider | >= 4.57.0 |
| Docker Provider | 3.6.2 |
| Null Provider | 3.2.4 |

## 🚀 Usage

### Basic Python API

```hcl
module "python_api" {
  source = "../serverless"

  region               = "centralus"
  resource_group_name  = "myapp-prod-rg"
  product_alias        = "myapp"
  env_alias            = "prod"
  product_display_name = "My Application API"
  
  module_name          = "api"
  function_name        = "handler"
  function_description = "Main API handler"
  module_type          = "python"
  
  package_type         = "LocalZip"
  package_path         = "${path.module}/dist/function.zip"
  
  publisher_email      = "admin@mycompany.com"
  
  environment_variables = {
    ENVIRONMENT = "production"
    LOG_LEVEL   = "info"
  }
  
  # API Gateway
  api_version    = "v1"
  api_base_path  = "api"
  agent_endpoint = "chat"
  gateway_endpoints = [
    {
      function_name = "health"
      path          = "/health"
      method        = "GET"
    },
    {
      function_name = "chat"
      path          = "/chat"
      method        = "POST"
    }
  ]

  tags = {
    Environment = "production"
    Service     = "api"
  }
}

output "api_url" {
  value = module.python_api.api_url
}

output "function_app_url" {
  value = module.python_api.function_app_url
}
```

### Node.js API with Custom VNet

```hcl
module "nodejs_api" {
  source = "../serverless"

  region               = "centralus"
  resource_group_name  = "myapp-prod-rg"
  product_alias        = "myapp"
  env_alias            = "prod"
  product_display_name = "Node.js API"
  
  module_name          = "chat"
  function_name        = "handler"
  function_description = "Chat API endpoint"
  module_type          = "nodejs"
  
  package_type = "LocalZip"
  package_path = "${path.module}/dist/function.zip"
  
  publisher_email = "admin@mycompany.com"
  
  # Custom VNet configuration
  vnet_cidr             = "10.1.0.0/16"
  private_subnet_cidrs  = ["10.1.10.0/23", "10.1.12.0/23"]
  public_subnet_cidrs   = ["10.1.1.0/24", "10.1.2.0/24"]
  
  environment_variables = {
    NODE_ENV = "production"
  }
  
  api_version    = "v2"
  agent_endpoint = "chat"
  gateway_endpoints = [
    {
      function_name = "chat"
      path          = "/chat"
      method        = "POST"
    }
  ]
}
```

### With Redis for Session Storage

```hcl
module "serverless_api_redis" {
  source = "../serverless"

  region               = "centralus"
  resource_group_name  = "myapp-prod-rg"
  product_alias        = "myapp"
  env_alias            = "prod"
  product_display_name = "Serverless API with Redis"
  
  module_name          = "chat"
  function_name        = "handler"
  function_description = "Chat API with Redis session storage"
  module_type          = "python"
  
  package_type = "LocalZip"
  package_path = "${path.module}/dist/function.zip"
  
  publisher_email = "admin@mycompany.com"
  
  # Enable Redis Enterprise for session storage
  create_redis_cluster = true
  is_production       = true  # Uses Balanced_B5 SKU
  
  environment_variables = {
    ENVIRONMENT = "production"
    # Redis URL automatically injected as AK_SESSION__REDIS__URL
  }
  
  api_version    = "v1"
  agent_endpoint = "chat"
  gateway_endpoints = [
    {
      function_name = "chat"
      path          = "/chat"
      method        = "POST"
    }
  ]
}
```

### With Cosmos DB for Session Storage

```hcl
module "serverless_api_cosmosdb" {
  source = "../serverless"

  region               = "centralus"
  resource_group_name  = "myapp-prod-rg"
  product_alias        = "myapp"
  env_alias            = "prod"
  product_display_name = "Serverless API with Cosmos DB"
  
  module_name          = "chat"
  function_name        = "handler"
  function_description = "Chat API with Cosmos DB session storage"
  module_type          = "python"
  
  package_type = "LocalZip"
  package_path = "${path.module}/dist/function.zip"
  
  publisher_email = "admin@mycompany.com"
  
  # Enable Cosmos DB Table API for session storage
  create_cosmosdb_cluster                    = true
  cosmosdb_consistency_level                 = "Session"
  cosmosdb_public_network_access_enabled     = false
  cosmosdb_point_in_time_recovery_enabled    = true
  cosmosdb_server_side_encryption_enabled    = true
  
  environment_variables = {
    ENVIRONMENT = "production"
    # Cosmos DB connection details automatically injected:
    # AK_SESSION__COSMOSDB__TABLE_NAME
    # AK_SESSION__COSMOSDB__TABLE_ENDPOINT
    # AK_SESSION__COSMOSDB__CONNECTION_STRING
  }
  
  api_version    = "v1"
  agent_endpoint = "chat"
  gateway_endpoints = [
    {
      function_name = "chat"
      path          = "/chat"
      method        = "POST"
    }
  ]
}
```

### Production Setup with Existing VNet

```hcl
module "production_api" {
  source = "../serverless"

  region               = "centralus"
  resource_group_name  = "enterprise-prod-rg"
  product_alias        = "enterprise"
  env_alias            = "prod"
  product_display_name = "Enterprise API"
  
  module_name          = "core-api"
  function_name        = "handler"
  function_description = "Production API handler"
  module_type          = "python"
  
  package_type = "LocalZip"
  package_path = "${path.module}/dist/function.zip"
  
  publisher_email = "api-admin@enterprise.com"
  
  # Use existing VNet
  vnet_id                   = "/subscriptions/.../virtualNetworks/enterprise-vnet"
  vnet_name                 = "enterprise-vnet"
  vnet_resource_group_name  = "enterprise-network-rg"
  private_subnet_ids        = ["infrastructure-subnet", "function-subnet"]
  
  # Enable both Redis and Cosmos DB
  create_redis_cluster    = true
  create_cosmosdb_cluster = true
  is_production          = true  # Uses Basic_1 APIM SKU
  
  environment_variables = {
    ENVIRONMENT           = "production"
    LOG_LEVEL            = "warn"
    ENABLE_METRICS       = "true"
  }
  
  api_version    = "v1"
  agent_endpoint = "enterprise"
  gateway_endpoints = [
    {
      function_name = "health"
      path          = "/health"
      method        = "GET"
    },
    {
      function_name = "enterprise"
      path          = "/enterprise"
      method        = "POST"
    },
    {
      function_name = "status"
      path          = "/status"
      method        = "GET"
    }
  ]
  
  tags = {
    Environment  = "production"
    Compliance   = "SOC2"
    CostCenter   = "Engineering"
    Criticality  = "high"
  }
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
| `module_type` | Runtime type: `python` or `nodejs` | `string` | `"python"` | no |
| `module_name` | Module name for resource identification | `string` | n/a | yes |
| `is_production` | Enable production features (Basic APIM SKU) | `bool` | `false` | no |
| `package_path` | Path to function ZIP package | `string` | n/a | yes |
| `package_type` | Deployment type: `LocalZip` or `Image` | `string` | `"LocalZip"` | no |
| `environment_variables` | Environment variables for function | `map(string)` | `{}` | no |
| `function_name` | Function name suffix | `string` | n/a | yes |
| `function_description` | Function description | `string` | `""` | no |
| `tags` | Additional tags for resources | `map(string)` | `{}` | no |

### API Management Configuration

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|:--------:|
| `api_version` | API version for endpoint path | `string` | `"v1"` | no |
| `agent_endpoint` | Default API endpoint name | `string` | `"HttpExample"` | no |
| `api_base_path` | Base path segment for API | `string` | `"api"` | no |
| `publisher_name` | API Management publisher name | `string` | `"Your Organization"` | no |
| `publisher_email` | API Management publisher email | `string` | n/a | yes |
| `gateway_endpoints` | List of API endpoints to expose | `list(object)` | `[]` | no |

### VNet Configuration

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|:--------:|
| `vnet_cidr` | CIDR block for new VNet | `string` | `"10.0.0.0/16"` | no |
| `private_subnet_cidrs` | Private subnet CIDRs | `list(string)` | `["10.0.3.0/24", "10.0.4.0/24"]` | no |
| `public_subnet_cidrs` | Public subnet CIDRs | `list(string)` | `["10.0.1.0/24", "10.0.2.0/24"]` | no |
| `vnet_id` | Existing VNet ID | `string` | `null` | no |
| `vnet_name` | Existing VNet name | `string` | `null` | no |
| `vnet_resource_group_name` | Existing VNet resource group | `string` | `null` | no |
| `private_subnet_ids` | Existing private subnet names | `list(string)` | `null` | no |

### State Management Configuration

#### Redis Configuration
| Name | Description | Type | Default | Required |
|------|-------------|------|---------|:--------:|
| `create_redis_cluster` | Enable Azure Managed Redis Enterprise | `bool` | `true` | no |

**Redis Environment Variables (Auto-injected when enabled)**:
- `AK_SESSION__REDIS__URL`: Complete Redis connection URL with authentication

#### Cosmos DB Configuration
| Name | Description | Type | Default | Required |
|------|-------------|------|---------|:--------:|
| `create_cosmosdb_cluster` | Enable Cosmos DB Table API | `bool` | `true` | no |
| `cosmosdb_consistency_level` | Cosmos DB consistency level | `string` | `"Session"` | no |
| `cosmosdb_public_network_access_enabled` | Enable public access for Cosmos DB | `bool` | `true` | no |
| `cosmosdb_point_in_time_recovery_enabled` | Enable PITR for Cosmos DB | `bool` | `false` | no |
| `cosmosdb_server_side_encryption_enabled` | Enable encryption for Cosmos DB | `bool` | `false` | no |
| `cosmosdb_key_vault_key_id` | Key Vault key ID for Cosmos DB encryption | `string` | `null` | no |

**Cosmos DB Environment Variables (Auto-injected when enabled)**:
- `AK_SESSION__COSMOSDB__TABLE_NAME`: Table name (`session_store`)
- `AK_SESSION__COSMOSDB__TABLE_ENDPOINT`: Table API endpoint URL
- `AK_SESSION__COSMOSDB__CONNECTION_STRING`: Connection string

## 📤 Outputs

| Name | Description | Example |
|------|-------------|---------|
| `function_app_url` | Function App default hostname | `myapp-prod-api-handler.azurewebsites.net` |
| `function_app_name` | Function App name | `myapp-prod-api-handler` |
| `api_management_gateway_url` | APIM Gateway URL | `https://myapp-prod-apim-flex.azure-api.net` |
| `api_url` | Complete API URL with base path and version | `https://myapp-prod-apim-flex.azure-api.net/api/v1` |
| `storage_account_name` | Storage account name for Function App | `myappproddeploy1234` |
| `application_insights_connection_string` | Application Insights connection string (sensitive) | `InstrumentationKey=...` |
| `function_identity_principal_id` | Function App managed identity principal ID | `12345678-1234-1234-1234-123456789012` |

## ✨ Features

### ⚡ Azure Functions Flex Consumption

**Next-Generation Serverless**:
- **Flex Consumption Plan**: Latest Azure Functions hosting plan with enhanced performance
- **VNet Integration**: Native VNet integration with subnet delegation requirement
- **Runtime Support**: Python 3.12 and Node.js 22 runtimes
- **Scaling**: Up to 100 instances (production) or 50 instances (development)
- **Memory**: 2048 MB instance memory for optimal performance

**Subnet Delegation Requirement**:
```hcl
# The function subnet MUST have Microsoft.App/environments delegation
# This is automatically configured by the VNet module for subnet 2
virtual_network_subnet_id = local.function_subnet_id  # Uses delegated subnet
```

**Storage Configuration**:
- Uses System-assigned managed identity for storage authentication
- Automatic ZIP package upload to blob storage
- Deployment container with private access

### 🌐 API Management Integration

**Consumption/Basic Tier**:
- **Development**: Consumption_0 SKU (serverless, pay-per-call)
- **Production**: Basic_1 SKU (dedicated gateway, SLA included)

**API Gateway Architecture**:
```
https://{apim-name}.azure-api.net/{api_base_path}/{version}/{endpoint}
```

**Function Integration**:
- Single backend configuration for all functions
- Function key authentication automatically configured
- Path rewriting to route to specific functions
- Application Insights integration for monitoring

### 🔒 Network Security and VNet Integration

**VNet Architecture**:
- **Infrastructure Subnet**: APIM and private endpoints (subnet 1)
- **Function Subnet**: Azure Functions with Microsoft.App/environments delegation (subnet 2)

**Critical Subnet Requirements**:
```hcl
# Function subnet MUST have delegation for Flex Consumption
delegation {
  name = "flex-function-delegation"
  service_delegation {
    name = "Microsoft.App/environments"
    actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
  }
}
```

**Security Features**:
- All traffic routed through VNet (`WEBSITE_VNET_ROUTE_ALL = "1"`)
- Private endpoints for Redis and Cosmos DB
- System-assigned managed identity
- Storage account access via managed identity

### 💾 State Management Options

#### Redis Enterprise Integration
**When `create_redis_cluster = true`**:
- Azure Managed Redis Enterprise deployed with private endpoint
- Connection details automatically injected as environment variables
- SKU selection based on `is_production` flag

#### Cosmos DB Table API Integration
**When `create_cosmosdb_cluster = true`**:
- Cosmos DB with Table API capability for DynamoDB compatibility
- Private endpoint integration
- Connection details automatically injected as environment variables

## 🏗️ Architecture

**Azure Functions Flex Consumption with VNet Integration**:
                        ┌─────────────────────┐
                        │   Internet          │
                        └──────────┬──────────┘
                                   │ HTTPS
                                   ▼
┌─────────────────────────────────────────────────────────────┐
│                API Management                               │
│              (Consumption/Basic)                            │
│                                                             │
│              • Not subnet bound                             │
│              • Managed service                              │
│              • Routes to Function App                       │
└─────────────────────┬───────────────────────────────────────┘
                      │ Function Key Auth
                      │ /api/v1/{endpoint}
                      ▼
┌──────────────────────────────────────────────────────────────┐
│                       VNet                                   │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐ │
│  │              Infrastructure Subnet                     │ │
│  │                                                        │ │
│  │  ┌─────────────────────────────────────────────────┐  │ │
│  │  │           Private Endpoints                     │  │ │
│  │  │           • Redis Enterprise                    │  │ │
│  │  │           • Cosmos DB                           │  │ │
│  │  │           • Storage Account                     │  │ │
│  │  └─────────────────────────────────────────────────┘  │ │
│  └────────────────────────────────────────────────────────┘ │
│                                                              │
│  ┌─────────────┬────────────────────────────────────────┐   │
│  │             │    Function Subnet (Delegated)         │   │
│  │             ▼    Microsoft.App/environments          │   │
│  │  ┌─────────────────────────────────────────────────┐ │   │
│  │  │     Azure Functions Flex Consumption           │ │   │
│  │  │     • VNet Integration Enabled                 │ │   │
│  │  │     • System-Assigned Identity                 │ │   │
│  │  │     • Storage via Managed Identity             │ │   │
│  │  │                                                │ │   │
│  │  │  ┌─────────────────────────────────────────┐  │ │   │
│  │  │  │        Function App                     │  │ │   │
│  │  │  │  • Python 3.12 / Node.js 22           │  │ │   │
│  │  │  │  • 2048 MB Memory                      │  │ │   │
│  │  │  │  • Auto-scaling (50-100 instances)     │  │ │   │
│  │  │  │  • Application Insights Integration    │  │ │   │
│  │  │  │                                        │  │ │   │
│  │  │  │  ┌─────────────────────────────────┐  │  │ │   │
│  │  │  │  │     HTTP Triggers               │  │  │ │   │
│  │  │  │  │  • /health → health()           │  │  │ │   │
│  │  │  │  │  • /chat → chat()               │  │  │ │   │
│  │  │  │  │  • /status → status()           │  │  │ │   │
│  │  │  │  └─────────────────────────────────┘  │  │ │   │
│  │  │  └─────────────────────────────────────────┘  │ │   │
│  │  └─────────────────────────────────────────────────┘ │   │
│  └───────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌───────────────────────────────────────────────────────┐  │
│  │                Public Subnets                         │  │
│  │          ┌────────────────────────┐                   │  │
│  │          │   NAT Gateway          │                   │  │
│  │          │   (Outbound Internet)  │                   │  │
│  │          └────────────────────────┘                   │  │
│  └───────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘

                      Traffic Flow:
                      1. Internet → APIM Gateway
                      2. APIM → Function App (via Function Key)
                      3. Function App → HTTP Triggers
                      4. Functions → Private Endpoints (Redis/Cosmos)
```
**Key Architecture Points**:
- **Flex Consumption Plan**: Latest Azure Functions hosting with enhanced performance
- **Subnet Delegation**: Function subnet requires Microsoft.App/environments delegation
- **VNet Integration**: All traffic routed through VNet for security
- **APIM Tiers**: Consumption (dev) vs Basic (prod) based on `is_production` flag

## 🎯 Best Practices

### 1. Function Package Optimization

```bash
# Create optimized ZIP package
cd your-function-code/
zip -r ../function.zip . -x "*.pyc" "__pycache__/*" "tests/*" "*.md"
```

### 2. Environment-Specific Configuration

```hcl
locals {
  config = {
    dev = {
      is_production = false
      create_redis_cluster = false
      create_cosmosdb_cluster = true
    }
    prod = {
      is_production = true
      create_redis_cluster = true
      create_cosmosdb_cluster = true
    }
  }
  env_config = local.config[var.env_alias]
}

module "api" {
  # ... other config
  is_production           = local.env_config.is_production
  create_redis_cluster    = local.env_config.create_redis_cluster
  create_cosmosdb_cluster = local.env_config.create_cosmosdb_cluster
}
```

### 3. Function Code Structure

```python
# Python function example
import azure.functions as func
import logging
import os

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

@app.route(route="health", methods=["GET"])
def health(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse("OK", status_code=200)

@app.route(route="chat", methods=["POST"])
def chat(req: func.HttpRequest) -> func.HttpResponse:
    # Access environment variables
    redis_url = os.environ.get('AK_SESSION__REDIS__URL')
    cosmos_table = os.environ.get('AK_SESSION__COSMOSDB__TABLE_NAME')
    
    # Your function logic here
    return func.HttpResponse("Chat response", status_code=200)
```

### 4. Gateway Endpoints Configuration

```hcl
gateway_endpoints = [
  {
    function_name = "health"      # Function name in your code
    path          = "/health"     # API path
    method        = "GET"         # HTTP method
  },
  {
    function_name = "chat"
    path          = "/chat"
    method        = "POST"
  },
  {
    function_name = "status"
    path          = "/status"
    method        = "GET"
  }
]

# Results in API endpoints:
# GET  /api/v1/health  -> health function
# POST /api/v1/chat    -> chat function
# GET  /api/v1/status  -> status function
```

## 💰 Cost Optimization

### Monthly Cost Estimate (centralus)

**Azure Functions Flex Consumption**:
- **Execution Time**: $0.000016/GB-second
- **Requests**: $0.20 per million requests
- **Memory**: 2048 MB (2 GB) per instance

**Example**: 1M requests/month, 200ms avg execution:
```
Execution cost: 1,000,000 × 0.2s × 2GB × $0.000016 = $6.40
Request cost: 1,000,000 × $0.0000002 = $0.20
Total: ~$6.60/month
```

**Additional Costs**:
- **APIM Consumption**: $0.035 per 10,000 calls
- **APIM Basic**: ~$140/month (production)
- **Storage Account**: ~$2-5/month
- **Application Insights**: Based on data ingestion
- **Redis Enterprise**: ~$200-800/month (if enabled)
- **Cosmos DB**: Pay per RU consumed (if enabled)

**Cost Saving Tips**:
1. Use Consumption APIM tier for development
2. Optimize function execution time
3. Use Cosmos DB serverless for variable workloads
4. Monitor Application Insights data ingestion

## 🔍 Troubleshooting

### Function Deployment Issues

**Issue**: Function deployment fails or times out

**Solutions**:
1. Check VNet integration and subnet delegation
2. Verify storage account connectivity
3. Ensure function package is valid ZIP format
4. Check Application Insights logs for deployment errors

### VNet Integration Problems

**Issue**: Function cannot access private resources

**Solutions**:
1. Verify subnet has Microsoft.App/environments delegation:
   ```bash
   az network vnet subnet show \
     --resource-group myapp-prod-rg \
     --vnet-name myapp-prod-vnet \
     --name myapp-prod-private-subnet-2
   ```

2. Check `WEBSITE_VNET_ROUTE_ALL` is set to "1"
3. Verify private endpoints are in correct subnet
4. Test DNS resolution from function

### APIM Cannot Reach Function

**Issue**: API Management returns 502/503 errors

**Solutions**:
1. Verify function keys are correctly configured
2. Check function app is running and responsive
3. Test function directly using function URL
4. Review APIM backend configuration

### Redis/Cosmos DB Connection Issues

**Solutions**:
- Verify environment variables are properly injected
- Check private endpoint connectivity
- Test connections using function logs
- Ensure managed identity has proper permissions

## 📊 Monitoring and Observability

### Application Insights Integration

**Automatic Monitoring**:
- Function execution logs and metrics
- HTTP request tracing through APIM
- Dependency tracking (Redis, Cosmos DB)
- Custom telemetry support

**Key Metrics to Monitor**:
- Function execution duration and success rate
- APIM request/response times and error rates
- Redis connection pool metrics (if enabled)
- Cosmos DB request units consumption (if enabled)

### Log Analytics Queries

```kusto
// Function execution logs
traces
| where cloud_RoleName == "myapp-prod-api-handler"
| order by timestamp desc

// HTTP requests through APIM
requests
| where cloud_RoleName == "myapp-prod-apim-flex"
| summarize avg(duration), count() by bin(timestamp, 5m)

// Function performance
performanceCounters
| where cloud_RoleName == "myapp-prod-api-handler"
| where counter == "% Processor Time"
| summarize avg(value) by bin(timestamp, 5m)
```

## 📚 Additional Resources

- [Azure Functions Flex Consumption Documentation](https://docs.microsoft.com/en-us/azure/azure-functions/flex-consumption-plan)
- [API Management Documentation](https://docs.microsoft.com/en-us/azure/api-management/)
- [Azure Functions VNet Integration](https://docs.microsoft.com/en-us/azure/azure-functions/functions-networking-options)
- [Azure Managed Redis Documentation](https://docs.microsoft.com/en-us/azure/azure-cache-for-redis/)

## 🔗 Related Modules

- [VNet Module](../common/modules/vnet/) - For custom VNet configurations with proper subnet delegation
- [Redis Module](../common/modules/redis/) - For standalone Redis Enterprise clusters
- [Cosmos Module](../common/modules/cosmos/) - For standalone Cosmos DB Table API instances

---

**Note**: This module uses Azure Functions Flex Consumption plan which requires subnet delegation for Microsoft.App/environments. The VNet module automatically configures this delegation for the function subnet (subnet 2). Ensure your Azure subscription has the necessary resource providers registered for Functions and API Management.

## License

Unless otherwise specified, all content, including all source code files and documentation files in this repository are:

Copyright (c) 2025-2026 Yaala Labs.

Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with the License. You may obtain a copy of the License at

http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the License for the specific language governing permissions and limitations under the License.