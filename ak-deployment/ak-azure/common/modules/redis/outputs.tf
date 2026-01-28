output "url" {
  value = "redis://${azurerm_managed_redis.redis.hostname}:${azurerm_managed_redis.redis.default_database[0].port}"
}

output "redis_private_ip" {
  value = azurerm_private_endpoint.redis.private_service_connection[0].private_ip_address
}

output "primary_key" {
  value = azurerm_managed_redis.redis.default_database[0].primary_access_key
  sensitive = true
}

output "full_redis_url" {
  value =  "rediss://:${azurerm_managed_redis.redis.default_database[0].primary_access_key}@${azurerm_managed_redis.redis.hostname}:${azurerm_managed_redis.redis.default_database.0.port}"
}
