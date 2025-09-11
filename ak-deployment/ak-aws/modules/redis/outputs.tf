output "url" {
  #TODO update redis:// to rediss:// when SSL is enabled
  value       = "redis://${aws_elasticache_cluster.redis.cache_nodes[0].address}:${aws_elasticache_cluster.redis.cache_nodes[0].port}"
  description = "Redis URL"
}