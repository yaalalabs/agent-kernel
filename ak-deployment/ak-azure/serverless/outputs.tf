output "function_app_url" {
  description = "Function App default hostname"
  value       = azurerm_function_app_flex_consumption.function.default_hostname
}

output "function_app_id" {
  description = "Function App resource ID"
  value       = azurerm_function_app_flex_consumption.function.id
}

output "function_app_name" {
  description = "Function App name"
  value       = azurerm_function_app_flex_consumption.function.name
}

output "api_management_gateway_url" {
  description = "API Management gateway URL"
  value       = azurerm_api_management.apim.gateway_url
}

output "api_management_id" {
  description = "API Management resource ID"
  value       = azurerm_api_management.apim.id
}

output "api_url" {
  description = "Complete API URL with base path and version"
  value       = var.api_base_path != null && var.api_base_path != "" ? "${azurerm_api_management.apim.gateway_url}/${var.api_base_path}/${var.api_version}" : "${azurerm_api_management.apim.gateway_url}/${var.api_version}"
}

output "private_subnet_ids" {
  description = "Private subnet IDs"
  value       = local.subnet_ids
}

output "storage_account_name" {
  description = "Storage account name for Function App"
  value       = azurerm_storage_account.function_storage.name
}

output "application_insights_connection_string" {
  description = "Application Insights connection string"
  value       = azurerm_application_insights.function_insights.connection_string
  sensitive   = true
}

output "function_identity_principal_id" {
  description = "Function App managed identity principal ID"
  value       = azurerm_function_app_flex_consumption.function.identity[0].principal_id
}

output "redis_private_ip" {
  value = module.redis[0].redis_private_ip
}