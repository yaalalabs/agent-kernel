data "azurerm_resource_group" "rg" {
  name = var.resource_group_name
}

data "azurerm_client_config" "current" {}

locals {
  function_app_name = "${var.product_alias}-${var.env_alias}-${var.module_name}-${var.function_name}"
}

# Use existing VNet if provided
data "azurerm_virtual_network" "existing" {
  count = var.vnet_id != null ? 1 : 0
  name  = var.vnet_name
  resource_group_name = var.vnet_resource_group_name
}

data "azurerm_subnet" "private" {
  count = var.vnet_id != null ? length(var.private_subnet_cidrs) : 0
  name  = "private-subnet-${count.index}"
  virtual_network_name = var.vnet_name
  resource_group_name  = var.vnet_resource_group_name
}

# Storage Account for Function App
resource "azurerm_storage_account" "function_storage" {
  name                     = "${var.product_alias}${var.env_alias}hurisa"
  resource_group_name      = data.azurerm_resource_group.rg.name
  location                 = var.region
  account_tier             = "Standard"
  account_replication_type = "LRS"
  public_network_access_enabled = true

  network_rules {
    default_action = "Allow"
  }

  tags = var.tags
}

# Storage Container for Flex Consumption deployment
resource "azurerm_storage_container" "function_deployment" {
  name                  = "${lower(local.function_app_name)}-deployment"
  storage_account_id    = azurerm_storage_account.function_storage.id
  container_access_type = "private"
}

# Upload the function package zip to the container
resource "azurerm_storage_blob" "function_package" {
  name                   = "app.zip"
  storage_account_name   = azurerm_storage_account.function_storage.name
  storage_container_name = azurerm_storage_container.function_deployment.name
  type                   = "Block"
  source                 = var.package_path
}

# Give the function app's system identity permission to read the deployment container
resource "azurerm_role_assignment" "func_storage_blob_contributor" {
  scope                = azurerm_storage_account.function_storage.id
  role_definition_name = "Storage Blob Data Contributor"  # Allows read + write + delete on blobs/containers
  principal_id         = azurerm_function_app_flex_consumption.function.identity[0].principal_id

  depends_on = [azurerm_function_app_flex_consumption.function]
}
# Application Insights
resource "azurerm_application_insights" "function_insights" {
  name                = "${local.function_app_name}-insights"
  location            = var.region
  resource_group_name = data.azurerm_resource_group.rg.name
  application_type    = "web"
  tags                = var.tags
}

# Service Plan with FC1 SKU for Flex Consumption
resource "azurerm_service_plan" "function_plan" {
  name                = "${local.function_app_name}-plan"
  location            = var.region
  resource_group_name = data.azurerm_resource_group.rg.name
  os_type             = "Linux"
  sku_name            = "FC1"
  tags                = var.tags
}

# Flex Consumption Function App
resource "azurerm_function_app_flex_consumption" "function" {
  name                = local.function_app_name
  location            = var.region
  resource_group_name = data.azurerm_resource_group.rg.name
  service_plan_id     = azurerm_service_plan.function_plan.id

  # Storage configuration for Flex (use identity auth)
  storage_container_type      = "blobContainer"
  storage_container_endpoint  = "${azurerm_storage_account.function_storage.primary_blob_endpoint}${azurerm_storage_container.function_deployment.name}"
  storage_authentication_type = "SystemAssignedIdentity"  # Preferred over connection string

  # Runtime configuration
  runtime_name    = var.module_type == "python" ? "python" : "node"
  runtime_version = var.module_type == "python" ? "3.11" : "22"

  # Scaling
  maximum_instance_count = var.is_production ? 100 : 50
  instance_memory_in_mb  = 2048

  site_config {
    application_insights_connection_string = azurerm_application_insights.function_insights.connection_string
    vnet_route_all_enabled                 = true

    cors {
      allowed_origins = ["*"]
    }
  }

  # App Settings (removed WEBSITE_RUN_FROM_PACKAGE)
  app_settings = merge(
    var.environment_variables,
    {
      "AzureWebJobsFeatureFlags"              = "EnableWorkerIndexing"
      "APPLICATIONINSIGHTS_CONNECTION_STRING" = azurerm_application_insights.function_insights.connection_string
      "WEBSITE_VNET_ROUTE_ALL"                = "1"
      "WEBSITE_DNS_SERVER"                    = "168.63.129.16"
    },
    local.redis_url != null ? {
      "AK_SESSION_REDIS_URL" = local.redis_url
    } : {},
    local.cosmosdb_table_name != null ? {
      "AK_SESSION_COSMOSDB_TABLE_NAME"    = local.cosmosdb_table_name
      "AK_SESSION_COSMOSDB_TABLE_ENDPOINT" = local.cosmosdb_table_endpoint
      "AK_SESSION_COSMOSDB_PRIMARY_KEY"   = local.cosmosdb_primary_key
    } : {}
  )

  virtual_network_subnet_id = local.function_subnet_id

  identity {
    type = "SystemAssigned"
  }

  tags = var.tags

  lifecycle {
    ignore_changes = [
      app_settings["WEBSITE_CONTENTSHARE"]
    ]
  }
}

# Trigger deployment using Azure CLI (runs after infra is ready)
resource "null_resource" "deploy_function_code" {
  triggers = {
    # Re-run if the zip changes
    package_hash = filemd5(var.package_path)
  }

  provisioner "local-exec" {
    command = <<EOT
      az functionapp deployment source config-zip \
        --resource-group ${data.azurerm_resource_group.rg.name} \
        --name ${local.function_app_name} \
        --src ${var.package_path}
    EOT
  }

  depends_on = [
    azurerm_function_app_flex_consumption.function,
    azurerm_storage_blob.function_package,
    azurerm_role_assignment.func_storage_blob_contributor
  ]
}