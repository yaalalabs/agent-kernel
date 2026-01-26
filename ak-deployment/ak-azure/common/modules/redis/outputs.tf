# output "url" {
#   value       = "redis://${azurerm_private_endpoint.redis.private_service_connection[0].private_ip_address}:${var.port}"
  
# }

output "url" {
  value = "redis://${azurerm_redis_cache.redis.hostname}:${var.port}"
}

output "primary_access_key" {
  value     = azurerm_redis_cache.redis.primary_access_key
  sensitive = true
}

output "redis_private_ip" {
  value = local.use_subnet_redis ?  "" : azurerm_private_endpoint.redis[0].private_service_connection[0].private_ip_address
}
