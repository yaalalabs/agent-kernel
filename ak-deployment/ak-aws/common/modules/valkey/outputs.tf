output "url" {
  #TODO update valkey:// to valkeys:// when SSL is enabled
  value       = "valkey://${aws_elasticache_replication_group.valkey.primary_endpoint_address}:${var.port}"
  description = "Valkey URL"
}
