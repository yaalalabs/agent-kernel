data "azurerm_resource_group" "current_group" {
  name = var.resource_group_name
}

data "azurerm_client_config" "current" {}

data "azurerm_virtual_network" "vnet" {
  name                = var.vnet_name
  resource_group_name = data.azurerm_resource_group.current_group.name
}
data "azurerm_subnet" "function_subnet" {
  name                 = var.function_subnet_name
  virtual_network_name = data.azurerm_virtual_network.vnet.name
  resource_group_name  = data.azurerm_virtual_network.vnet.resource_group_name
}
# Cosmos DB Account (Table API)
resource "azurerm_cosmosdb_account" "account" {
  name                = "${var.product_alias}-${var.env_alias}-${var.module_name}-cosmos"
  location            = data.azurerm_resource_group.current_group.location
  resource_group_name = data.azurerm_resource_group.current_group.name
  offer_type          = "Standard"
  kind                = "GlobalDocumentDB"

  # Enable Table API capability
  capabilities {
    name = "EnableTable"
  }

  # Serverless capability (PAY_PER_REQUEST equivalent)
  dynamic "capabilities" {
    for_each = var.billing_mode == "PAY_PER_REQUEST" ? [1] : []
    content {
      name = "EnableServerless"
    }
  }

  # Consistency level (Table API supports all levels)
  consistency_policy {
    consistency_level       = var.consistency_level
    max_interval_in_seconds = var.consistency_level == "BoundedStaleness" ? 5 : null
    max_staleness_prefix    = var.consistency_level == "BoundedStaleness" ? 100 : null
  }

  geo_location {
    location          = data.azurerm_resource_group.current_group.location
    failover_priority = 0
  }

  backup {
    type                = var.point_in_time_recovery_enabled ? "Continuous" : "Periodic"
    interval_in_minutes = var.point_in_time_recovery_enabled ? null : 240
    retention_in_hours  = var.point_in_time_recovery_enabled ? null : 8
    storage_redundancy  = "Local"
  }

  public_network_access_enabled = var.public_network_access_enabled

  key_vault_key_id = var.server_side_encryption_enabled ? var.key_vault_key_id : null

  tags = var.tags
}

resource "azurerm_cosmosdb_table" "table" {
  name                = "${var.product_alias}-${var.env_alias}-${var.module_name}-${var.table_name}"
  resource_group_name = data.azurerm_resource_group.current_group.name
  account_name        = azurerm_cosmosdb_account.account.name

  dynamic "autoscale_settings" {
    for_each = var.billing_mode == "PROVISIONED" && var.autoscale_max_throughput != null ? [1] : []
    content {
      max_throughput = var.autoscale_max_throughput
    }
  }

  throughput = var.billing_mode == "PROVISIONED" && var.autoscale_max_throughput == null ? var.provisioned_throughput : null
}

resource "azurerm_private_dns_zone" "cosmos_table" {
  name                = "privatelink.table.cosmos.azure.com"
  resource_group_name = data.azurerm_resource_group.current_group.name
}

resource "azurerm_private_dns_zone_virtual_network_link" "cosmos_dns_link" {
  name                  = "cosmos-dns-link"
  resource_group_name   = data.azurerm_resource_group.current_group.name
  private_dns_zone_name = azurerm_private_dns_zone.cosmos_table.name
  virtual_network_id    = data.azurerm_virtual_network.vnet.id
}

resource "azurerm_private_endpoint" "cosmos_table" {
  name                = "${var.product_alias}-${var.env_alias}-cosmos-table-pe"
  location            = data.azurerm_resource_group.current_group.location
  resource_group_name = data.azurerm_resource_group.current_group.name
  subnet_id           = var.subnet_id 

  private_service_connection {
    name                           = "cosmos-table-conn"
    private_connection_resource_id = azurerm_cosmosdb_account.account.id
    subresource_names              = ["Table"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "cosmos-dns"
    private_dns_zone_ids = [azurerm_private_dns_zone.cosmos_table.id]
  }
}

resource "azurerm_network_security_group" "cosmos_nsg" {
  count               = var.create_NSG ? 1 : 0
  name                = "${var.product_alias}-${var.env_alias}-${var.module_name}-cosmos-nsg"
  location            = data.azurerm_resource_group.current_group.location
  resource_group_name = data.azurerm_resource_group.current_group.name
  tags                = var.tags
}

resource "azurerm_network_security_rule" "allow_cosmos_from_function" {
  count                       = var.create_NSG ? 1 : 0
  name                        = "Allow-Cosmos-From-Function"
  priority                    = 100
  direction                   = "Inbound"
  access                      = "Allow"
  protocol                    = "Tcp"
  source_address_prefix       = data.azurerm_subnet.function_subnet.address_prefix
  source_port_range           = "*"
  destination_address_prefix  = "*"
  destination_port_range      = "*"
  resource_group_name         = data.azurerm_resource_group.current_group.name
  network_security_group_name = azurerm_network_security_group.cosmos_nsg[0].name
}

resource "azurerm_subnet_network_security_group_association" "cosmos_subnet_nsg_assoc" {
  count                     = var.create_NSG ? 1 : 0
  subnet_id                 = var.subnet_id
  network_security_group_id = azurerm_network_security_group.cosmos_nsg[0].id
}