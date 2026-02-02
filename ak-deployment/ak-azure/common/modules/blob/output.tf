output "source_storage_blob_container_path" {
  value       = "${azurerm_storage_account.source_storage.name}/${azurerm_storage_container.source_storage_container.name}"
  description = "Source blob container path (format: storage-account-name/container-name)"
}

output "source_storage_account_name" {
  value       = azurerm_storage_account.source_storage.name
  description = "Storage account name"
}

output "source_storage_container_name" {
  value       = azurerm_storage_container.source_storage_container.name
  description = "Blob container name"
}

output "source_storage_blob_endpoint" {
  value       = azurerm_storage_account.source_storage.primary_blob_endpoint
  description = "Primary blob endpoint URL"
}

output "azure_source_storage_id" {
  value = azurerm_storage_account.source_storage.id
  description = "Azure Storage Account ID"
}