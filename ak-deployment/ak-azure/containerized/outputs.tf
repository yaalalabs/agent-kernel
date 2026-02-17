output "container_app_fqdn" {
  description = "Fully qualified domain name of the Container App"
  value       = azurerm_container_app.app.ingress[0].fqdn
}

output "container_app_name" {
  description = "Name of the Container App"
  value       = azurerm_container_app.app.name
}

output "container_app_id" {
  description = "ID of the Container App"
  value       = azurerm_container_app.app.id
}

output "container_app_environment_id" {
  description = "ID of the Container App Environment"
  value       = azurerm_container_app_environment.env.id
}

output "api_management_gateway_url" {
  description = "Gateway URL of the API Management service"
  value       = azurerm_api_management.apim.gateway_url
}

output "api_management_name" {
  description = "Name of the API Management service"
  value       = azurerm_api_management.apim.name
}

output "api_base_url" {
  description = "Base URL for the API"
  value       = "${azurerm_api_management.apim.gateway_url}/${var.api_base_path != null && var.api_base_path != "" ? "${var.api_base_path}/" : ""}${var.api_version}"
}

output "log_analytics_workspace_id" {
  description = "ID of the Log Analytics Workspace"
  value       = azurerm_log_analytics_workspace.container_logs.id
}

output "application_insights_connection_string" {
  description = "Connection string for Application Insights"
  value       = azurerm_application_insights.container_insights.connection_string
  sensitive   = true
}

output "application_insights_instrumentation_key" {
  description = "Instrumentation key for Application Insights"
  value       = azurerm_application_insights.container_insights.instrumentation_key
  sensitive   = true
}

output "container_registry_login_server" {
  description = "Login server of the Container Registry"
  value       = module.docker_image.login_server
}

output "vnet_id" {
  description = "ID of the Virtual Network"
  value       = local.vnet_id
}

output "subnet_id" {
  description = "ID of the subnet used by Container Apps"
  value       = local.subnet_ids
}

output "redis_url" {
  description = "Redis connection URL (if enabled)"
  value       = local.redis_url
  sensitive   = true
}

output "cosmosdb_table_name" {
  description = "CosmosDB table name (if enabled)"
  value       = local.cosmosdb_table_name
}

output "cosmosdb_endpoint" {
  description = "CosmosDB endpoint (if enabled)"
  value       = local.cosmosdb_table_endpoint
  sensitive   = true
}

output "gateway_endpoints" {
  description = "Map of configured gateway endpoints"
  value = {
    for key, ep in local.gateway_endpoints_map :
    key => {
      path   = ep.path
      method = ep.method
      url    = "${azurerm_api_management.apim.gateway_url}${ep.path}"
    }
  }
}
