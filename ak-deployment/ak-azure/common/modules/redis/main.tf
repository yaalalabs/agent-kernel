data "azurerm_resource_group" "current_group" {
  name = var.resource_group_name
}

data "azurerm_client_config" "current" {}

# Get the VNet for private endpoint
data "azurerm_virtual_network" "vnet" {
  name                = var.vnet_name
  resource_group_name = var.vnet_resource_group_name != null ? var.vnet_resource_group_name : data.azurerm_resource_group.current_group.name
}

data "azurerm_subnet" "redis_subnet" {
  name                 = var.subnet_name
  virtual_network_name = data.azurerm_virtual_network.vnet.name
  resource_group_name  = data.azurerm_virtual_network.vnet.resource_group_name
}

data "azurerm_subnet" "function_subnet" {
  name                 = var.function_subnet
  virtual_network_name = data.azurerm_virtual_network.vnet.name
  resource_group_name  = data.azurerm_virtual_network.vnet.resource_group_name
}

resource "azurerm_network_security_rule" "allow_redis_from_function" {
  name                        = "Allow-Redis-From-Flex"
  priority                    = 100
  direction                   = "Inbound"
  access                      = "Allow"
  protocol                    = "Tcp"
  source_address_prefix       = data.azurerm_subnet.function_subnet.address_prefix
  source_port_range           = "*"
  destination_address_prefix  = "*"
  destination_port_range      = "6379"
  resource_group_name         = data.azurerm_resource_group.current_group.name
  network_security_group_name = azurerm_network_security_group.redis_nsg.name
}

resource "azurerm_subnet_network_security_group_association" "redis_subnet_nsg_assoc" {
  subnet_id                 = data.azurerm_subnet.redis_subnet.id
  network_security_group_id = azurerm_network_security_group.redis_nsg.id
}

locals {
  use_subnet_redis = var.sku_name == "Premium" && var.is_production
}

resource "azurerm_redis_cache" "redis" {

  name                = "${var.product_alias}-${var.env_alias}-${var.module_name}-redis"
  location            = data.azurerm_resource_group.current_group.location
  resource_group_name = data.azurerm_resource_group.current_group.name

  subnet_id = local.use_subnet_redis ? data.azurerm_subnet.redis_subnet.id : null

  capacity = var.node_capacity
  family   = var.node_family
  sku_name = var.sku_name

  public_network_access_enabled = false

  non_ssl_port_enabled = true

  redis_configuration {
    authentication_enabled = true
  }

  tags = var.tags

  lifecycle {
    ignore_changes = [location]
  }
}

resource "azurerm_network_security_group" "redis_nsg" {
  name                = "${var.product_alias}-${var.env_alias}-${var.module_name}-redis-nsg"
  location            = data.azurerm_resource_group.current_group.location
  resource_group_name = data.azurerm_resource_group.current_group.name

  tags = var.tags
}


# Private Endpoint for Redis(need this when we are not binding the redis to a subnet)
resource "azurerm_private_endpoint" "redis" {
  count               = local.use_subnet_redis ? 0 : 1
  name                = "${var.product_alias}-${var.env_alias}-${var.module_name}-redis-pe"
  location            = data.azurerm_resource_group.current_group.location
  resource_group_name = data.azurerm_resource_group.current_group.name
  subnet_id           = data.azurerm_subnet.redis_subnet.id

  private_service_connection {
    name                           = "${var.product_alias}-${var.env_alias}-${var.module_name}-redis-psc"
    private_connection_resource_id = azurerm_redis_cache.redis.id
    subresource_names              = ["redisCache"]
    is_manual_connection           = false
  }

  tags = var.tags
}

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
  tags                  = var.tags
  lifecycle {
    ignore_changes = [
      virtual_network_id
    ]
  }
}
