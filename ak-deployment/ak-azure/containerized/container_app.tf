# Container Apps Environment
resource "azurerm_container_app_environment" "env" {
  name                = "${var.product_alias}-${var.env_alias}-${var.module_name}-env"
  location            = var.region
  resource_group_name = data.azurerm_resource_group.rg.name

  # VNet integration
  infrastructure_subnet_id       = local.function_subnet_id
  internal_load_balancer_enabled = true

  log_analytics_workspace_id = azurerm_log_analytics_workspace.container_logs.id
  tags                       = var.tags

  lifecycle {
    ignore_changes = [ infrastructure_resource_group_name ]
  }
}

# Log Analytics Workspace for Container Apps
resource "azurerm_log_analytics_workspace" "container_logs" {
  name                = "${var.product_alias}-${var.env_alias}-${var.module_name}-logs"
  location            = var.region
  resource_group_name = data.azurerm_resource_group.rg.name
  sku                 = "PerGB2018"
  retention_in_days   = 90

  tags = var.tags
}

# Application Insights for Container Apps
resource "azurerm_application_insights" "container_insights" {
  name                = "${var.product_alias}-${var.env_alias}-${var.module_name}-insights"
  location            = var.region
  resource_group_name = data.azurerm_resource_group.rg.name
  workspace_id        = azurerm_log_analytics_workspace.container_logs.id
  application_type    = "web"

  tags = var.tags
}

# Container App
resource "azurerm_container_app" "app" {
  name                         = "${var.product_alias}-${var.env_alias}-${var.module_name}-app"
  container_app_environment_id = azurerm_container_app_environment.env.id
  resource_group_name          = data.azurerm_resource_group.rg.name
  revision_mode                = "Single"

  # Registry configuration for ACR
  registry {
    server               = module.docker_image.login_server
    username             = module.docker_image.admin_username
    password_secret_name = "acr-password"
  }

  # Secret for ACR password
  secret {
    name  = "acr-password"
    value = module.docker_image.admin_password
  }

  # Add Redis password secret if Redis is enabled
  dynamic "secret" {
    for_each = var.create_redis_cluster ? [1] : []
    content {
      name  = "redis-password"
      value = local.redis_password
    }
  }

  # Add CosmosDB connection string secret if CosmosDB is enabled
  dynamic "secret" {
    for_each = var.create_cosmosdb_cluster ? [1] : []
    content {
      name  = "cosmosdb-connection-string"
      value = local.cosmosdb_connection_string
    }
  }

  # Add CosmosDB primary key secret if CosmosDB is enabled
  dynamic "secret" {
    for_each = var.create_cosmosdb_cluster ? [1] : []
    content {
      name  = "cosmosdb-primary-key"
      value = local.cosmosdb_primary_key
    }
  }

  template {
    min_replicas = var.container_min_replicas
    max_replicas = var.container_max_replicas

    container {
      name   = "${var.product_alias}-${var.env_alias}-${var.module_name}-container"
      image  = "${module.docker_image.docker_image_uri}:latest"
      cpu    = var.is_production ? "1.0" : "0.5"
      memory = var.is_production ? "2Gi" : "1Gi"

      # Environment variables
      dynamic "env" {
        for_each = merge(
          var.environment_variables,
          local.redis_url != null ? {
            "AK_SESSION__REDIS__URL" = local.full_redis_url
          } : {},
          local.cosmosdb_table_name != null ? {
            "AK_SESSION__COSMOSDB__TABLE_NAME"        = local.cosmosdb_table_name
            "AK_SESSION__COSMOSDB__TABLE_ENDPOINT"    = local.cosmosdb_table_endpoint
            "AK_SESSION__COSMOSDB__CONNECTION_STRING" = "" # Will use secret reference
          } : {},
          {
            "APPLICATIONINSIGHTS_CONNECTION_STRING" = azurerm_application_insights.container_insights.connection_string
          }
        )
        content {
          name  = env.key
          value = env.value != "" ? env.value : null

          # Use secret reference for empty values (they'll be populated from secrets)
          secret_name = env.value == "" ? (
            env.key == "AK_SESSION__COSMOSDB__CONNECTION_STRING" ? "cosmosdb-connection-string" : null
          ) : null
        }
      }

      # Liveness probe
      liveness_probe {
        transport = "HTTP"
        port      = var.container_port
        path      = var.container_health_check_path

        initial_delay           = 10
        interval_seconds        = 30
        timeout                 = 5
        failure_count_threshold = 3
      }

      # Readiness probe
      readiness_probe {
        transport = "HTTP"
        port      = var.container_port
        path      = var.container_health_check_path

        interval_seconds        = 30
        timeout                 = 5
        failure_count_threshold = 3
        success_count_threshold = 1
      }

      # Startup probe
      startup_probe {
        transport = "HTTP"
        port      = var.container_port
        path      = var.container_health_check_path

        interval_seconds        = 10
        timeout                 = 5
        failure_count_threshold = 3
      }
    }

    # HTTP scale rule based on concurrent requests
    http_scale_rule {
      name                = "http-scaling"
      concurrent_requests = var.container_scale_concurrent_requests
    }
  }

  # Ingress configuration
  ingress {
    external_enabled = true
    target_port      = var.container_port
    transport        = "http"

    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  # Identity for accessing Azure resources
  identity {
    type = "SystemAssigned"
  }

  tags = var.tags

  depends_on = [
    azurerm_container_app_environment.env,
    module.docker_image
  ]
}

# Role assignment for Container App to access CosmosDB (if enabled)
resource "azurerm_role_assignment" "container_cosmosdb" {
  count                = var.create_cosmosdb_cluster ? 1 : 0
  scope                = module.cosmos[0].cosmosdb_account_id
  role_definition_name = "Cosmos DB Account Reader Role"
  principal_id         = azurerm_container_app.app.identity[0].principal_id

  depends_on = [azurerm_container_app.app]
}
