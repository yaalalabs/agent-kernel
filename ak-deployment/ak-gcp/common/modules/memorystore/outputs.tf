output "host" {
  description = "Redis instance hostname"
  value       = google_redis_instance.redis.host
}

output "port" {
  description = "Redis instance port"
  value       = google_redis_instance.redis.port
}

output "url" {
  description = "Redis connection URL"
  value       = "redis://${google_redis_instance.redis.host}:${google_redis_instance.redis.port}"
}

output "auth_string" {
  description = "Redis AUTH string (password)"
  value       = google_redis_instance.redis.auth_string
  sensitive   = true
}

output "full_redis_url" {
  description = "Redis URL with auth and SSL options (ssl_cert_reqs=none skips cert verification — safe on private VPC)"
  value       = var.auth_enabled ? "rediss://:${google_redis_instance.redis.auth_string}@${google_redis_instance.redis.host}:${google_redis_instance.redis.port}?ssl_cert_reqs=none" : "redis://${google_redis_instance.redis.host}:${google_redis_instance.redis.port}"
  sensitive   = true
}
