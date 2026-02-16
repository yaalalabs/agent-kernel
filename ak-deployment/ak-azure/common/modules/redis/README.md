# Redis Enterprise Module (Common Module)

This module provisions Azure Managed Redis (Enterprise) with private endpoint integration and sensible defaults for session storage and caching workloads.

**⚠️ Important Service Notice**: Azure Cache for Redis (Basic, Standard, Premium) is retiring on September 30, 2028, and Azure Cache for Redis Enterprise is retiring on March 30, 2027. This module uses **Azure Managed Redis**, which is Microsoft's recommended replacement service that provides improved performance, cost efficiency, and the latest Redis innovations.

## 📋 Overview

This module creates a fully managed Redis Enterprise instance with:

- 🏗️ **Azure Managed Redis Enterprise**: Uses the latest Redis Enterprise solution with enhanced performance
- 🔒 **Private Network Access**: Disabled public access with private endpoint integration
- 🛡️ **Network Security**: Optional NSG creation with rules for secure access from function subnets
- 🔐 **Encrypted Communication**: TLS encryption enabled by default for client connections
- 📊 **Production-Ready SKUs**: Automatic SKU selection based on environment (Balanced_B0 for dev, Balanced_B5 for prod)
- 🏷️ **Consistent Naming**: Follows project naming conventions with `-redis-enterprise` suffix

Perfect for session storage, caching, and real-time applications requiring high-performance Redis functionality.

## Features
- Opinionated naming: `<product>-<env>-<module>-redis-enterprise`
- Private endpoint with DNS integration (`privatelink.redis.azure.net`)
- Encrypted client protocol (TLS) by default
- No clustering policy (single instance) for simplicity
- Access key authentication enabled
- System-assigned managed identity
- Optional Network Security Group with function subnet access rules
- Pass-through tags

## Inputs
Key inputs (see `variables.tf` for full list):
- `product_alias`, `env_alias`, `module_name`, `tags`
- `resource_group_name` (required) — Azure resource group name
- `vnet_name` (required) — Virtual Network name for private endpoint
- `vnet_resource_group_name` (optional) — VNet resource group if different from current RG
- `subnet_name` (required) — Subnet name for private endpoint placement
- `function_subnet` (required) — Function subnet name for NSG rules
- `is_production` (default: false) — Controls SKU selection (B0 vs B5)
- `create_NSG` (default: false) — Create Network Security Group for enhanced security

## Outputs
- `url` — Basic Redis connection URL (`redis://hostname:port`)
- `full_redis_url` — Complete Redis URL with authentication (`rediss://:password@hostname:port`)
- `primary_key` — Primary access key (sensitive)
- `redis_private_ip` — Private IP address of the Redis instance (Private Endpoint IP)

## Usage

### Basic Redis for Development
```hcl
module "production_redis" {
  source = "yaalalabs/ak-common/azurerm//modules/redis"

  product_alias            = var.product_alias
  env_alias                = var.env_alias
  module_name              = var.module_name
  resource_group_name      = var.resource_group_name
  vnet_resource_group_name = var.vnet_resource_group_name

  # Network configuration
  vnet_name       = local.vnet_name
  subnet_name     = local.subnet_name
  function_subnet = local.function_subnet_name

  # Production settings
  is_production = true|false
  create_NSG    = true|false # if the network rules should be created from the module it-self (Not Managed by other modules)

  tags = var.tags
  depends_on = [module.vnet]
}
```

### Referencing from Serverless/Containerized stacks
The module outputs can be used to configure applications with Redis connectivity:

#### Container App Configuration
```hcl
# In container_app.tf - Environment variables
env {
  name  = "AK_SESSION__REDIS__URL"
  value = module.redis[0].full_redis_url
}

# Secret for Redis password
secret {
  name  = "redis-password"
  value = module.redis[0].primary_key
}
```

#### Azure Function Configuration
```hcl
# In function app settings
app_settings = merge(var.environment_variables, {
  "AK_SESSION__REDIS__URL" = module.redis[0].full_redis_url
})
```

## Architecture

### Private Endpoint Integration
The module creates:
- **Private DNS Zone**: `privatelink.redis.azure.net` for name resolution
- **Private Endpoint**: Secure connection to Redis Enterprise instance
- **DNS Zone Virtual Network Link**: Links private DNS to your VNet
- **Optional NSG**: Network Security Group with rules allowing access from function subnet

### SKU Selection
- **Development** (`is_production = false`): `Balanced_B0` - Cost-effective for dev/test
- **Production** (`is_production = true`): `Balanced_B5` - Higher performance and availability

### Security Features
- **Public Access**: Disabled by default (`public_network_access = "Disabled"`)
- **Encryption**: TLS encryption enabled for all client connections
- **Authentication**: Access key authentication enabled
- **Network Isolation**: Private endpoint ensures traffic stays within your VNet

## Connection Examples

### Python (redis-py)
```python
import redis
import os

# Using full Redis URL (recommended)
redis_url = os.getenv('AK_SESSION__REDIS__URL')
r = redis.from_url(redis_url, ssl_cert_reqs=None)

# Or using individual components
r = redis.Redis(
    host='your-redis-hostname',
    port=10000,
    password='your-access-key',
    ssl=True,
    ssl_cert_reqs=None
)
```

### Node.js (ioredis)
```javascript
const Redis = require('ioredis');

// Using connection URL
const redis = new Redis(process.env.AK_SESSION__REDIS__URL, {
  tls: {
    rejectUnauthorized: false
  }
});

// Or using configuration object
const redis = new Redis({
  host: 'your-redis-hostname',
  port: 10000,
  password: 'your-access-key',
  tls: {
    rejectUnauthorized: false
  }
});
```

## Versioning
- Module uses Azure Managed Redis (Enterprise) - the latest Redis offering from Microsoft
- Compatible with Redis 6.x and 7.x features
- Supports all standard Redis commands and data structures

## Notes
- **High Availability**: Currently disabled (`high_availability_enabled = false`) for cost optimization
- **Clustering**: Uses `NoCluster` policy for simplicity - suitable for most session storage use cases
- **Port**: Redis Enterprise typically uses port 10000 (provided by azure) (not the standard 6379)
- **TLS**: All connections are encrypted by default
- **Monitoring**: Integrates with Azure Monitor for metrics and alerting
- **Backup**: Enterprise tier includes automatic backups and point-in-time recovery
- **Scaling**: Can be scaled up/down without data loss (depending on SKU)

## Security Best Practices
1. **Network Isolation**: Always use private endpoints in production
2. **NSG Rules**: Create specific NSG rules for your application subnets
3. **TLS**: Ensure all client connections use TLS encryption
4. **Monitoring**: Enable Azure Monitor alerts for connection and performance metrics
5. **Least Privilege**: Use separate Redis instances for different environments/applications

## Troubleshooting

### Creation Failures
- Ensure the subnet if you provide yourself, do have nessaasry deligations to support private endpoint
- If you get an write error on the creation life-cycle, check if the region you are using have Redis Enterprise capacity. You might need to change the region

### Connection Issues
- Verify private endpoint DNS resolution
- Check NSG rules allow traffic from your application subnet
- Ensure TLS is enabled in your Redis client
- Validate access key is correct

### Performance Issues
- Consider upgrading SKU for higher throughput
- Monitor memory usage and connection counts
- Review client connection pooling settings
- Check network latency between app and Redis

### DNS Resolution
- Verify private DNS zone is linked to your VNet
- Check that private endpoint has correct IP assignment
- Test DNS resolution from your application subnet