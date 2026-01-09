data "azurerm_resource_group" "current_group" {
  name = var.resource_group_name
}

data "azurerm_client_config" "current" {}

locals {
  subscription_hash    = substr(md5(data.azurerm_subscription.current.subscription_id), 0, 8)
  storage_account_name = substr(replace("${var.product_alias}${var.env_alias}src${local.subscription_hash}", "/[^a-z0-9]/", ""), 0, 24)
  container_name       = "sources"

  key_vault_uri = var.s3_kms_key_id != null ? regex("(https://[^/]+)", var.s3_kms_key_id)[0] : null
}

resource "azurerm_storage_account" "source_storage" {
  name                     = local.storage_account_name
  resource_group_name      = data.azurerm_resource_group.current_group.name
  location                 = var.region
  account_tier             = "Standard"
  account_replication_type = var.is_production ? "GRS" : "LRS"
  account_kind             = "StorageV2"

  min_tls_version                 = "TLS1_2"
  https_traffic_only_enabled      = true
  allow_nested_items_to_be_public = false

  blob_properties {
    versioning_enabled = var.is_production ? true : false

    dynamic "delete_retention_policy" {
      for_each = var.is_production ? [1] : []
      content {
        days = 7
      }
    }
  }

  # Infrastructure encryption
  infrastructure_encryption_enabled = var.is_production ? true : false

  network_rules {
    default_action = "Allow"
    bypass         = ["AzureServices"]
  }

  tags = merge({
    Name            = local.storage_account_name
    Region          = var.region
    isBackupEnabled = var.is_production ? "true" : "false"
    backupType      = "critical"
    ResourceName    = "AppSourceBucket"
  }, var.s3_bucket_tags)
}

resource "azurerm_storage_container" "source_storage_container" {
  name                  = local.container_name
  storage_account_id    = azurerm_storage_account.source_storage.id
  container_access_type = "private"
}

# Customer-managed key encryption (if KMS key is provided)

resource "azurerm_storage_account_customer_managed_key" "source_storage_cmk" {
  count              = var.is_production && var.s3_kms_key_id != null ? 1 : 0
  storage_account_id = azurerm_storage_account.source_storage.id
  key_vault_uri      = local.key_vault_uri
  key_name           = split("/", var.s3_kms_key_id)[4]
}

# Role assignment for Azure Functions
resource "azurerm_role_assignment" "function_storage_reader" {
  count                = var.function_principal_id != null ? 1 : 0
  scope                = azurerm_storage_account.source_storage.id
  role_definition_name = "Storage Blob Data Reader"
  principal_id         = var.function_principal_id
}
