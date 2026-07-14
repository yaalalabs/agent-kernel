output "url" {
  value       = "valkey://${aws_elasticache_replication_group.valkey.primary_endpoint_address}:${var.port}"
  description = "Valkey URL"
}
