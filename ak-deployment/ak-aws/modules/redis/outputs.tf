output "endpoint" {
  value       = aws_elasticache_cluster.redis.cache_nodes[0].address
  description = "Redis endpoint address"
}

output "port" {
  value       = aws_elasticache_cluster.redis.cache_nodes[0].port
  description = "Redis port number"
}