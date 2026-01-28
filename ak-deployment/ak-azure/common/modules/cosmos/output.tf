output "table_name" {
  description = "Table name"
  value       = azurerm_cosmosdb_table.table.name
}

output "table_id" {
  description = "Table ID"
  value       = azurerm_cosmosdb_table.table.id
}

output "endpoint" {
  description = "Cosmos DB Table API endpoint"
  value       = azurerm_cosmosdb_account.account.endpoint
}

output "table_endpoint" {
  description = "Table API specific endpoint"
  value       = "https://${azurerm_cosmosdb_account.account.name}.table.cosmos.azure.com"
}

output "primary_key" {
  description = "Primary access key"
  value       = azurerm_cosmosdb_account.account.primary_key
  sensitive   = true
}

output "secondary_key" {
  description = "Secondary access key"
  value       = azurerm_cosmosdb_account.account.secondary_key
  sensitive   = true
}

output "primary_readonly_key" {
  description = "Primary read-only key"
  value       = azurerm_cosmosdb_account.account.primary_readonly_key
  sensitive   = true
}

output "secondary_readonly_key" {
  description = "Secondary read-only key"
  value       = azurerm_cosmosdb_account.account.secondary_readonly_key
  sensitive   = true
}

output "full_connection_string" {
  description = "Cosmos DB Table API connection string"
  value = "DefaultEndpointsProtocol=https;AccountName=${azurerm_cosmosdb_account.account.name};AccountKey=${azurerm_cosmosdb_account.account.primary_key};TableEndpoint=https://${azurerm_cosmosdb_account.account.name}.table.cosmos.azure.com:443/;"
}