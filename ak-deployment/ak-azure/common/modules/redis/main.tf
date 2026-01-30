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
  count                       = var.create_NSG ? 1 : 0
  name                        = "Allow-Redis-From-Flex"
  priority                    = 100
  direction                   = "Inbound"
  access                      = "Allow"
  protocol                    = "Tcp"
  source_address_prefix       = data.azurerm_subnet.function_subnet.address_prefix
  source_port_range           = "*"
  destination_address_prefix  = "*"
  destination_port_range      = "*"
  resource_group_name         = data.azurerm_resource_group.current_group.name
  network_security_group_name = azurerm_network_security_group.redis_nsg[0].name
}

resource "azurerm_subnet_network_security_group_association" "redis_subnet_nsg_assoc" {
  count                     = var.create_NSG ? 1 : 0
  subnet_id                 = data.azurerm_subnet.redis_subnet.id
  network_security_group_id = azurerm_network_security_group.redis_nsg[0].id
}

resource "azurerm_managed_redis" "redis" {
  name                      = "${var.product_alias}-${var.env_alias}-${var.module_name}-redis-enterprise"
  location                  = data.azurerm_resource_group.current_group.location
  resource_group_name       = data.azurerm_resource_group.current_group.name
  sku_name                  = var.is_production ? "Balanced_B5" : "Balanced_B0"
  high_availability_enabled = false
  public_network_access     = "Disabled"

  default_database {
    client_protocol                    = "Encrypted"
    clustering_policy                  = "NoCluster"
    access_keys_authentication_enabled = true
  }
  identity {
    type = "SystemAssigned"
  }
  tags = var.tags
}

resource "azurerm_network_security_group" "redis_nsg" {
  count               = var.create_NSG ? 1 : 0
  name                = "${var.product_alias}-${var.env_alias}-${var.module_name}-redis-nsg"
  location            = data.azurerm_resource_group.current_group.location
  resource_group_name = data.azurerm_resource_group.current_group.name

  tags = var.tags
}


# Private Endpoint for Redis(need this when we are not binding the redis to a subnet)
resource "azurerm_private_endpoint" "redis" {
  name                = "${var.product_alias}-${var.env_alias}-${var.module_name}-redis-pe"
  location            = data.azurerm_resource_group.current_group.location
  resource_group_name = data.azurerm_resource_group.current_group.name
  subnet_id           = data.azurerm_subnet.redis_subnet.id

  private_service_connection {
    name                           = "${var.product_alias}-${var.env_alias}-${var.module_name}-redis-psc"
    private_connection_resource_id = azurerm_managed_redis.redis.id
    subresource_names              = ["redisEnterprise"]
    is_manual_connection           = false
  }
  private_dns_zone_group {
    name                 = "redis-private-dns-zone-group"
    private_dns_zone_ids = [azurerm_private_dns_zone.redis.id]
  }
  depends_on = [azurerm_managed_redis.redis]
  tags       = var.tags
}

# Private DNS Zone for Redis
resource "azurerm_private_dns_zone" "redis" {
  name                = "privatelink.redis.azure.net"
  resource_group_name = data.azurerm_resource_group.current_group.name
  tags                = var.tags
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
