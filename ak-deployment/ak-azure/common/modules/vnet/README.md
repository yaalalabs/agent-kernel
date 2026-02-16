# VNet Module (Common Module)

A Terraform module for creating production-ready Azure Virtual Network infrastructure with public and private subnets, NAT gateway, and optimized routing for serverless and containerized applications.

## 📋 Overview

This module provisions a complete VNet networking stack following Azure best practices:

- 🌐 **Complete VNet**: DNS resolution and CIDR configuration (equivalent to AWS VPC)
- 🔒 **Private Subnets**: Two isolated subnets with specific purposes:
  - **Subnet 1** (`private-subnet-1`): For private endpoints, Redis, Cosmos DB, and other infrastructure
  - **Subnet 2** (`private-subnet-2`): Dedicated for Azure Functions with Flex consumption plan delegation
- 🌍 **Public Subnets**: Internet-accessible subnets for NAT gateway placement
- 🚪 **NAT Gateway**: Secure outbound internet access for private resources
- 🛣️ **Routing**: Automatic NAT gateway association with all private subnets
- 📍 **Service Endpoints**: Storage service endpoints on infrastructure subnet (subnet 1)
- ⚡ **Subnet Delegation**: Microsoft.App/environments delegation on function subnet (subnet 2)

Perfect for serverless architectures, Azure Functions requiring VNet integration, Container Apps, Redis/Cosmos DB instances, and any workload needing network isolation.

## 📋 Requirements

| Name | Version |
|------|---------|
| Terraform | >= 1.9.5 |
| Azure Provider | >= 4.0.0 |

## 🚀 Usage

### Basic Example

```hcl
module "vnet" {
  source = "../../common/modules/vnet"

  resource_group_name  = "myapp-prod-rg"
  location            = "East US"
  vnet_cidr           = "10.0.0.0/16"
  public_subnet_cidrs = ["10.0.1.0/24", "10.0.2.0/24"]
  private_subnet_cidrs = ["10.0.3.0/24", "10.0.4.0/24"]
  product_alias       = "myapp"
  env_alias           = "prod"
  
  tags = {
    Environment = "production"
    ManagedBy   = "terraform"
  }
}
```

### Complete Serverless Stack

```hcl
module "vnet" {
  source = "../../common/modules/vnet"

  resource_group_name  = var.resource_group_name
  location            = var.region
  vnet_cidr           = "10.0.0.0/16"
  public_subnet_cidrs = ["10.0.1.0/24", "10.0.2.0/24"]
  private_subnet_cidrs = ["10.0.3.0/24", "10.0.4.0/24"]
  product_alias       = var.product_alias
  env_alias           = var.env_alias
  tags               = var.tags
}

# Azure Function using VNet integration
resource "azurerm_linux_function_app" "api" {
  name                = "myapp-api"
  resource_group_name = var.resource_group_name
  location           = var.region
  
  # Uses the delegated function subnet (subnet 2)
  virtual_network_subnet_id = module.vnet.private_subnet_ids[1]
  
  service_plan_id = azurerm_service_plan.main.id
}

# Redis in infrastructure subnet (subnet 1)
module "redis" {
  source = "../../common/modules/redis"

  product_alias       = var.product_alias
  env_alias          = var.env_alias
  module_name        = "cache"
  resource_group_name = var.resource_group_name
  vnet_name          = module.vnet.vnet_name
  subnet_name        = module.vnet.private_subnet_name  # subnet 1
  function_subnet    = module.vnet.function_subnet_name # subnet 2
}
```

## 📥 Inputs

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|:--------:|
| `resource_group_name` | Name of the Azure resource group | `string` | n/a | yes |
| `location` | Azure region for resources | `string` | `"eastus"` | no |
| `vnet_cidr` | CIDR block for the Virtual Network | `string` | `"10.0.0.0/16"` | no |
| `public_subnet_cidrs` | List of CIDR blocks for public subnets | `list(string)` | `["10.0.1.0/24", "10.0.2.0/24"]` | no |
| `private_subnet_cidrs` | List of CIDR blocks for private subnets | `list(string)` | `["10.0.3.0/24", "10.0.4.0/24"]` | no |
| `product_alias` | Short identifier for the product (e.g., "myapp") | `string` | n/a | yes |
| `env_alias` | Environment identifier (e.g., "dev", "staging", "prod") | `string` | n/a | yes |
| `tags` | Additional tags to apply to all resources | `map(string)` | `{}` | no |

## 📤 Outputs

| Name | Description | Example |
|------|-------------|---------|
| `vnet_id` | The ID of the Virtual Network | `/subscriptions/.../virtualNetworks/myapp-prod-vnet` |
| `vnet_name` | The name of the Virtual Network | `myapp-prod-vnet` |
| `public_subnet_ids` | List of public subnet IDs | `["/subscriptions/.../subnets/myapp-prod-public-subnet-1"]` |
| `private_subnet_ids` | List of private subnet IDs | `["/subscriptions/.../subnets/myapp-prod-private-subnet-1"]` |
| `private_subnet_name` | Name of the infrastructure subnet (subnet 1) | `myapp-prod-private-subnet-1` |
| `function_subnet_name` | Name of the function subnet (subnet 2) | `myapp-prod-private-subnet-2` |
| `nat_gateway_id` | ID of the NAT Gateway | `/subscriptions/.../natGateways/myapp-prod-nat` |
| `nat_public_ip_id` | ID of the NAT Gateway Public IP | `/subscriptions/.../publicIPAddresses/myapp-prod-nat-pip` |
| `nat_public_ip_address` | Public IP address of the NAT Gateway | `52.12.34.56` |

## ✨ Features

### 🌐 VNet Configuration

- **Address Space**: Customizable CIDR block, defaults to `10.0.0.0/16`
- **DNS Resolution**: Automatic DNS resolution within VNet
- **Tagging**: Automatic tagging with product and environment identifiers

### 🔒 Network Isolation

**Public Subnets**:
- Host NAT Gateway for private subnet internet access
- No direct resources deployed (reserved for future use)

**Private Subnet 1** (Infrastructure):
- **Purpose**: Private endpoints, Redis, Cosmos DB, storage accounts
- **Service Endpoints**: Microsoft.Storage enabled
- **No Delegation**: Available for any Azure resource
- **Naming**: `{product}-{env}-private-subnet-1`

**Private Subnet 2** (Functions):
- **Purpose**: Azure Functions with Flex consumption plan
- **Delegation**: Microsoft.App/environments for Container Apps and Functions
- **No Service Endpoints**: Clean subnet for function deployments
- **Naming**: `{product}-{env}-private-subnet-2`

### 🚪 Gateway Management

**NAT Gateway**:
- Standard SKU for production workloads
- Static public IP for consistent outbound traffic
- Associated with all private subnets
- Enables private resources to access internet securely

### ⚡ Subnet Specialization

**Infrastructure Subnet (Subnet 1)**:
```hcl
# Used for:
module "redis" {
  subnet_name = module.vnet.private_subnet_name  # subnet 1
}

module "cosmos" {
  subnet_id = module.vnet.private_subnet_ids[0]  # subnet 1
}
```

**Function Subnet (Subnet 2)**:
```hcl
# Used for:
resource "azurerm_linux_function_app" "api" {
  virtual_network_subnet_id = module.vnet.private_subnet_ids[1]  # subnet 2
}

resource "azurerm_container_app_environment" "env" {
  infrastructure_subnet_id = module.vnet.private_subnet_ids[1]  # subnet 2
}
```

## 🎯 Best Practices

### CIDR Planning

1. **Non-Overlapping CIDRs**: Ensure VNet CIDRs don't overlap if using VNet peering
2. **Subnet Sizing**: Plan subnet sizes based on expected resource count
3. **Future Growth**: Leave room for additional subnets

```hcl
# Good CIDR allocation for scalability
module "vnet" {
  vnet_cidr            = "10.0.0.0/16"     # 65,536 IPs
  public_subnet_cidrs  = [
    "10.0.0.0/24",   # 256 IPs per AZ
    "10.0.1.0/24"
  ]
  private_subnet_cidrs = [
    "10.0.10.0/23",  # 512 IPs for infrastructure
    "10.0.12.0/23"   # 512 IPs for functions
  ]
}
```

### Subnet Usage Guidelines

1. **Infrastructure Subnet**: Use for private endpoints, databases, caches
2. **Function Subnet**: Dedicated for Azure Functions and Container Apps
3. **Avoid Mixing**: Don't deploy infrastructure resources in function subnet

## ⚠️ Azure Functions Flex Limitations

**Important**: Azure Functions with Flex consumption plan have specific subnet requirements:

1. **Dedicated Subnet**: Functions require a subnet with Microsoft.App/environments delegation
2. **No Mixed Resources**: The delegated subnet should primarily be used for functions and container apps
3. **Subnet Size**: Minimum /27 (32 IPs) recommended for function scaling
4. **Regional Availability**: Flex consumption plan availability varies by region

**This module handles these requirements by**:
- Creating separate subnets for infrastructure vs. functions
- Applying proper delegation to the function subnet
- Providing clear output naming for easy identification

## 💰 Cost Considerations

**Cost Savings Tips**:
- Use service endpoints to avoid NAT Gateway data charges for Azure services
- Monitor outbound data transfer through Azure Monitor
- Consider Azure Firewall for advanced scenarios

## 🔍 Common Use Cases

### Azure Function with VNet Integration

```hcl
module "vnet" {
  source = "../../common/modules/vnet"
  
  product_alias       = "myapp"
  env_alias          = "prod"
  resource_group_name = var.resource_group_name
}

resource "azurerm_linux_function_app" "api" {
  name = "api"
  
  # Uses delegated function subnet
  virtual_network_subnet_id = module.vnet.private_subnet_ids[1]
  
  # Function can now access:
  # - Private resources (Redis, Cosmos DB) directly
  # - Internet via NAT Gateway
  # - Azure services via service endpoints
}
```

## 🔍 Troubleshooting

### Function Cannot Access Private Resources

**Issue**: Azure Function cannot connect to Redis/Cosmos DB
```
Error: Connection timeout to private endpoint
```

**Solutions**:
1. Verify function is using the correct subnet (subnet 2)
2. Check private endpoint is in infrastructure subnet (subnet 1)
3. Verify DNS resolution for private endpoints
4. Check NSG rules allow traffic between subnets

### Subnet Delegation Conflicts

**Issue**: Cannot deploy resources to function subnet
```
Error: Subnet is delegated to Microsoft.App/environments
```

**Solution**: Use the correct subnet for your resource type:
```hcl
# ✅ Correct - Infrastructure resources in subnet 1
module "redis" {
  subnet_name = module.vnet.private_subnet_name  # subnet 1
}

# ✅ Correct - Functions in subnet 2
resource "azurerm_linux_function_app" "api" {
  virtual_network_subnet_id = module.vnet.private_subnet_ids[1]  # subnet 2
}
```

## 📚 Additional Resources

- [Azure Virtual Network Documentation](https://docs.microsoft.com/en-us/azure/virtual-network/)
- [Azure Functions VNet Integration](https://docs.microsoft.com/en-us/azure/azure-functions/functions-networking-options)
- [NAT Gateway Pricing](https://azure.microsoft.com/en-us/pricing/details/virtual-network/)
- [Subnet Delegation](https://docs.microsoft.com/en-us/azure/virtual-network/subnet-delegation-overview)

## 🔗 Related Modules

- [Redis Module](../redis/) - Deploy Redis with private endpoints in subnet 1
- [Cosmos Module](../cosmos/) - Deploy Cosmos DB with private endpoints in subnet 1
---

**Note**: This module creates a single NAT Gateway for cost optimization. The two private subnets serve different purposes: subnet 1 for infrastructure with service endpoints, and subnet 2 for Azure Functions with proper delegation. Always use the appropriate subnet for your resource type to avoid deployment issues.