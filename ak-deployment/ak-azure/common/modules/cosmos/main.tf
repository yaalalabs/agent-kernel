data "azurerm_resource_group" "current_group" {
  name = var.resource_group_name
}

data "azurerm_client_config" "current" {}

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