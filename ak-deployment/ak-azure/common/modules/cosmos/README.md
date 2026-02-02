# Cosmos DB Table (Common Module)

This module provisions Azure Cosmos DB with Table API to provide DynamoDB-compatible functionality with sensible defaults and a naming convention consistent with the rest of the project.

It is intended to be consumed by both serverless and containerized stacks to create and manage Cosmos DB tables with Table API.

## Features
- Opinionated naming: defaults to `<product>-<env>-<module>-cosmos` for account and `<product>-<env>-<module>-<table_name>` for table
- PAY_PER_REQUEST (serverless) by default (can switch to PROVISIONED with optional autoscale)
- Table API capability enabled for DynamoDB compatibility
- Private endpoint integration with VNet
- Configurable consistency levels (Strong, BoundedStaleness, Session, ConsistentPrefix, Eventual)
- Point-in-time recovery (continuous backup) support
- Customer-managed encryption key support
- Network Security Group (NSG) creation for enhanced security
- Pass-through tags

## Inputs
Key inputs (see `variables.tf` for full list):
- `product_alias`, `env_alias`, `module_name`, `tags`
- `table_name` (required) — table name within the Cosmos DB account
- `resource_group_name` (required) — Azure resource group name
- `billing_mode` (default: PAY_PER_REQUEST), `provisioned_throughput`, `autoscale_max_throughput`
- `consistency_level` (default: Session)
- `point_in_time_recovery_enabled` (default: false)
- `server_side_encryption_enabled` (default: false), `key_vault_key_id`
- `public_network_access_enabled` (default: true)
- `vnet_name`, `subnet_id`, `function_subnet_name` — for private endpoint integration
- `create_NSG` (default: false) — create Network Security Group for enhanced security
- `read_capacity`, `write_capacity` — compatibility variables (not used in Azure)

## Outputs
- `table_name`, `table_id` — table identification
- `endpoint`, `table_endpoint` — Cosmos DB endpoints
- `primary_key`, `secondary_key` — access keys (sensitive)
- `primary_readonly_key`, `secondary_readonly_key` — read-only keys (sensitive)
- `full_connection_string` — complete Table API connection string
- `cosmosdb_account_id` — Cosmos DB account resource ID

## Usage

### Basic table (serverless, session store)
```hcl
module "session_table" {
  source = "../../common/modules/cosmos"

  product_alias       = var.product_alias
  env_alias           = var.env_alias
  module_name         = var.module_name
  table_name          = "session_store"
  resource_group_name = var.resource_group_name

  # VNet integration
  vnet_name            = local.vnet_name
  subnet_id            = local.subnet_ids
  function_subnet_name = local.function_subnet_name

  tags = var.tags
}
```

### Production table with enhanced security and backup
```hcl
module "orders_table" {
  source = "../../common/modules/cosmos"

  product_alias       = var.product_alias
  env_alias           = var.env_alias
  module_name         = "orders"
  table_name          = "orders_data"
  resource_group_name = var.resource_group_name

  # Enhanced consistency for critical data
  consistency_level = "Strong"

  # Enable backup and encryption
  point_in_time_recovery_enabled = true
  server_side_encryption_enabled = true
  key_vault_key_id               = var.key_vault_key_id

  # Network security
  public_network_access_enabled = false
  create_NSG                    = true
  vnet_name                     = local.vnet_name
  subnet_id                     = local.subnet_ids
  function_subnet_name          = local.function_subnet_name

  tags = var.tags
}
```

### Provisioned throughput with autoscale
```hcl
module "high_volume_table" {
  source = "../../common/modules/cosmos"

  product_alias       = var.product_alias
  env_alias           = var.env_alias
  module_name         = "analytics"
  table_name          = "events"
  resource_group_name = var.resource_group_name

  # Provisioned mode with autoscale
  billing_mode             = "PROVISIONED"
  autoscale_max_throughput = 4000  # Will autoscale from 400 to 4000 RU/s

  # VNet integration
  vnet_name            = local.vnet_name
  subnet_id            = local.subnet_ids
  function_subnet_name = local.function_subnet_name

  tags = var.tags
}
```

### Referencing from Serverless/Containerized stacks
- Add the module call in your stack (serverless or containerized) like shown above
- Export any outputs you need or pass connection details as environment variables to Functions or Container Apps

Example: pass connection details to a Container App via environment variables:
```hcl
# In container_app.tf
env {
  name  = "AK_SESSION__COSMOSDB__TABLE_NAME"
  value = module.cosmos[0].table_name
}

env {
  name  = "AK_SESSION__COSMOSDB__TABLE_ENDPOINT"
  value = module.cosmos[0].table_endpoint
}

env {
  name        = "AK_SESSION__COSMOSDB__CONNECTION_STRING"
  secret_name = "cosmosdb-connection-string"
}

# Secret for connection string
secret {
  name  = "cosmosdb-connection-string"
  value = module.cosmos[0].full_connection_string
}
```

## Architecture

### Private Endpoint Integration
The module creates:
- Private DNS zone (`privatelink.table.cosmos.azure.com`)
- Private endpoint for Table API access
- DNS zone virtual network link
- Optional Network Security Group with rules allowing access from function subnet

### Consistency Levels
Azure Cosmos DB Table API supports all consistency levels:
- **Strong**: Linearizability guarantee (highest consistency, highest latency)
- **BoundedStaleness**: Consistent prefix with bounded staleness
- **Session**: Consistent prefix with session consistency (default, good balance)
- **ConsistentPrefix**: Updates appear in order
- **Eventual**: Lowest consistency, lowest latency

### Billing Modes
- **PAY_PER_REQUEST** (Serverless): Automatically scales, pay per operation
- **PROVISIONED**: Fixed throughput, can use autoscale (400-4000 RU/s range)

## Versioning
- Module uses the latest Azure provider features for Cosmos DB Table API
- Compatible with Azure Resource Manager API version 2021-10-15 and later

## Notes
- **TTL Support**: Table API does not support TTL (Time-To-Live) configurations like DynamoDB. This is a known limitation of Azure Cosmos DB Table API compared to DynamoDB's native TTL feature.
- When using PROVISIONED capacity with autoscale, the minimum throughput is 400 RU/s
- For customer-managed encryption, provide `key_vault_key_id` from Azure Key Vault
- Private endpoint is always created when `vnet_name` and `subnet_id` are provided
- Network Security Group creation is optional but recommended for production environments
- The module creates a single table per instance - for multiple tables, instantiate the module multiple times

## Compatibility with DynamoDB
This module provides DynamoDB-compatible functionality through Azure Cosmos DB Table API:
- ✅ Key-value operations (Get, Put, Delete, Query, Scan)
- ✅ Batch operations
- ✅ Conditional operations
- ✅ Secondary indexes (through Cosmos DB's native indexing)
- ❌ TTL (Time-To-Live) - not supported in Table API
- ❌ Streams - not supported in Table API
- ❌ Global Secondary Indexes - use Cosmos DB's automatic indexing

## Security Best Practices
1. **Disable Public Access**: Set `public_network_access_enabled = false` for production
2. **Use Private Endpoints**: Always configure VNet integration for secure access
3. **Enable NSG**: Set `create_NSG = true` for additional network security. This is required when private endpoints are used.
4. **Customer-Managed Keys**: Use `server_side_encryption_enabled = true` with Key Vault
5. **Least Privilege**: Use read-only keys where possible
6. **Connection Strings**: Store connection strings as secrets, not environment variables