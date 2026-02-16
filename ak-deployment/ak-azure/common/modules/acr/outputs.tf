output "docker_image_uri" {
  description = "The ACR Docker image URI"
  value       = var.enabled ? "${azurerm_container_registry.acr[0].login_server}/${var.product_alias}-${var.env_alias}-${var.module_name}" : null
}

output "login_server" {
  description = "The ACR login server"
  value       = var.enabled ? azurerm_container_registry.acr[0].login_server : null
}

output "admin_username" {
  description = "The ACR admin username"
  value       = var.enabled ? azurerm_container_registry.acr[0].admin_username : null
}

output "admin_password" {
  description = "The ACR admin password"
  value       = var.enabled ? azurerm_container_registry.acr[0].admin_password : null
  sensitive   = true
}
