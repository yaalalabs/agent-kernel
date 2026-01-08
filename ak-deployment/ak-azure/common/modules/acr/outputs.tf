output "docker_image_uri" {
    description = "The ACR Docker image URI"
    value       = "${azurerm_container_registry.acr.login_server}/${local.image_name}"
}