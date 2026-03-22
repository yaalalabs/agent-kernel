data "azurerm_resource_group" "rg" {
  name = var.resource_group_name
}

data "azurerm_client_config" "current" {}

# Use existing VNet if provided
data "azurerm_virtual_network" "existing" {
  count               = var.vnet_id != null ? 1 : 0
  name                = var.vnet_name
  resource_group_name = var.vnet_resource_group_name
}

data "azurerm_subnet" "private" {
  count                = var.vnet_id != null ? 1 : 0
  name                 = var.private_subnet_ids[0]
  virtual_network_name = data.azurerm_virtual_network.existing[0].name
  resource_group_name  = var.vnet_resource_group_name
}

data "azurerm_subnet" "function_subnet" {
  count                = var.vnet_id != null ? 1 : 0
  name                 = var.private_subnet_ids[1]
  virtual_network_name = data.azurerm_virtual_network.existing[0].name
  resource_group_name  = var.vnet_resource_group_name
}

locals {
  # VNet configuration
  vnet_name            = var.vnet_id != null ? data.azurerm_virtual_network.existing[0].name : module.vnet[0].vnet_name
  subnet_name          = var.vnet_id != null ? data.azurerm_subnet.private[0].name : module.vnet[0].private_subnet_name
  function_subnet_name = var.vnet_id != null ? data.azurerm_subnet.function_subnet[0].name : module.vnet[0].function_subnet_name
  vnet_id              = var.vnet_id != null ? data.azurerm_virtual_network.existing[0].id : module.vnet[0].vnet_id
  vnet_cidr            = var.vnet_id != null ? data.azurerm_virtual_network.existing[0].address_space[0] : var.vnet_cidr
  subnet_ids           = var.vnet_id != null ? data.azurerm_subnet.private[0].id : module.vnet[0].private_subnet_ids[0]
  function_subnet_id   = var.vnet_id != null ? data.azurerm_subnet.function_subnet[0].id : module.vnet[0].private_subnet_ids[1]

  # Redis configuration
  redis_url      = var.create_redis_cluster == true ? module.redis[0].url : null
  redis_password = var.create_redis_cluster == true ? module.redis[0].primary_key : null
  full_redis_url = var.create_redis_cluster == true ? module.redis[0].full_redis_url : null

  # CosmosDB configuration
  cosmosdb_table_name        = var.create_cosmosdb_cluster == true ? module.cosmos[0].table_name : null
  cosmosdb_table_endpoint    = var.create_cosmosdb_cluster == true ? module.cosmos[0].table_endpoint : null
  cosmosdb_primary_key       = var.create_cosmosdb_cluster == true ? module.cosmos[0].primary_key : null
  cosmosdb_connection_string = var.create_cosmosdb_cluster == true ? module.cosmos[0].full_connection_string : null

  # API configuration
  api_base_segment = try(trim(var.api_base_path, "/"), "")
}

# VNet Module (creates new VNet if not provided)
module "vnet" {
  count                = var.vnet_id == null ? 1 : 0
  source               = "yaalalabs/ak-common/azurerm//modules/vnet"
  version              = "0.2.14"
  resource_group_name  = var.vnet_resource_group_name == null ? var.resource_group_name : var.vnet_resource_group_name
  location             = var.region
  product_alias        = var.product_alias
  env_alias            = var.env_alias
  private_subnet_cidrs = var.private_subnet_cidrs
  public_subnet_cidrs  = var.public_subnet_cidrs
  vnet_cidr            = var.vnet_cidr
  tags                 = var.tags
}

# Redis Module (optional)
module "redis" {
  count                    = var.create_redis_cluster == true ? 1 : 0
  source                   = "yaalalabs/ak-common/azurerm//modules/redis"
  version                  = "0.2.14"
  product_alias            = var.product_alias
  subnet_name              = local.subnet_name
  function_subnet          = local.function_subnet_name
  env_alias                = var.env_alias
  module_name              = var.module_name
  vnet_resource_group_name = var.vnet_resource_group_name
  resource_group_name      = var.resource_group_name
  tags                     = var.tags
  vnet_name                = local.vnet_name
  is_production            = var.is_production
  create_NSG               = false
  depends_on               = [module.vnet]
}

# CosmosDB Module
module "cosmos" {
  count                          = var.create_cosmosdb_cluster == true ? 1 : 0
  source                         = "yaalalabs/ak-common/azurerm//modules/cosmos"
  version                        = "0.2.14"
  product_alias                  = var.product_alias
  env_alias                      = var.env_alias
  module_name                    = var.module_name
  tags                           = var.tags
  vnet_name                      = local.vnet_name
  subnet_id                      = local.subnet_ids
  function_subnet_name           = local.function_subnet_name
  table_name                     = "session_store"
  resource_group_name            = var.resource_group_name
  consistency_level              = var.cosmosdb_consistency_level
  public_network_access_enabled  = var.cosmosdb_public_network_access_enabled
  point_in_time_recovery_enabled = var.cosmosdb_point_in_time_recovery_enabled
  server_side_encryption_enabled = var.cosmosdb_server_side_encryption_enabled
  key_vault_key_id               = var.cosmosdb_key_vault_key_id
  create_NSG                     = false
  depends_on                     = [module.vnet]
}

# Docker Image Module (ACR)
module "docker_image" {
  source              = "yaalalabs/ak-common/azurerm//modules/acr"
  version             = "0.2.14"
  enabled             = true
  env_alias           = var.env_alias
  module_name         = var.module_name
  product_alias       = var.product_alias
  source_path         = var.package_path
  resource_group_name = var.resource_group_name
  region              = var.region
}
