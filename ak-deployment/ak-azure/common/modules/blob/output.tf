output "source_storage_s3_bucket" {
  value       = "${azurerm_storage_account.source_storage.name}/${azurerm_storage_container.source_storage_container.name}"
  description = "Source storage bucket ID (format: storage-account-name/container-name)"
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