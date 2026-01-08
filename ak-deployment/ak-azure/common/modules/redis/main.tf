data "azurerm_resource_group" "current_group" {
  name = var.resource_group_name
}

data "azurerm_client_config" "current" {}

# Get the VNet for private endpoint
data "azurerm_virtual_network" "vnet" {
  name                = var.vnet_name
  resource_group_name = var.vnet_resource_group_name != "" ? var.vnet_resource_group_name : data.azurerm_resource_group.current_group.name
}

data "azurerm_subnet" "redis_subnet" {
  name                 = var.subnet_name
  virtual_network_name = data.azurerm_virtual_network.vnet.name
  resource_group_name  = data.azurerm_virtual_network.vnet.resource_group_name
}

# Azure Redis Cache
resource "azurerm_redis_cache" "redis" {
  name                = "${var.product_alias}-${var.env_alias}-${var.module_name}-redis"
  location            = data.azurerm_resource_group.current_group.location
  resource_group_name = data.azurerm_resource_group.current_group.name
  subnet_id           = data.azurerm_subnet.redis_subnet.id

  capacity = var.node_capacity
  family   = var.node_family
  sku_name = var.sku_name

  non_ssl_port_enabled = true

  public_network_access_enabled = false # Disable public access for security

  redis_configuration {
    authentication_enabled = false
  }

  tags = var.tags
}

# Private Endpoint for Redis(need this when we are not binding the redis to a subnet)
# resource "azurerm_private_endpoint" "redis" {
#   name                = "${var.product_alias}-${var.env_alias}-${var.module_name}-redis-pe"
#   location            = data.azurerm_resource_group.current_group.location
#   resource_group_name = data.azurerm_resource_group.current_group.name
#   subnet_id           = data.azurerm_subnet.redis_subnet.id

#   private_service_connection {
#     name                           = "${var.product_alias}-${var.env_alias}-${var.module_name}-redis-psc"
#     private_connection_resource_id = azurerm_redis_cache.redis.id
#     subresource_names              = ["redisCache"]
#     is_manual_connection           = false
#   }

#   tags = var.tags
# }

# Private DNS Zone for Redis
resource "azurerm_private_dns_zone" "redis" {
  name                = "privatelink.redis.cache.windows.net"
  resource_group_name = data.azurerm_resource_group.current_group.name

  tags = var.tags
}

# Link DNS Zone to VNet
resource "azurerm_private_dns_zone_virtual_network_link" "redis" {
  name                  = "${var.product_alias}-${var.env_alias}-${var.module_name}-redis-dns-link"
  resource_group_name   = data.azurerm_resource_group.current_group.name
  private_dns_zone_name = azurerm_private_dns_zone.redis.name
  virtual_network_id    = data.azurerm_virtual_network.vnet.id

  tags = var.tags
}

# # DNS A Record for Private Endpoint (enable this when we are not binding the redis to a subnet)
# resource "azurerm_private_dns_a_record" "redis" {
#   name                = azurerm_redis_cache.redis.name
#   zone_name           = azurerm_private_dns_zone.redis.name
#   resource_group_name = data.azurerm_resource_group.current_group.name
#   ttl                 = 300
#   records             = [azurerm_private_endpoint.redis.private_service_connection[0].private_ip_address]

#   tags = var.tags
# }
