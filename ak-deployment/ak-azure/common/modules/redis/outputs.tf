# output "url" {
#   value       = "redis://${azurerm_private_endpoint.redis.private_service_connection[0].private_ip_address}:${var.port}"
  
# }

output "url" {
    value = "redis://${azurerm_redis_cache.redis.hostname}:${var.port}"
}