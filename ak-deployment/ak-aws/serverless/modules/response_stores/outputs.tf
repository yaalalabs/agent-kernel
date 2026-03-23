# Redis outputs
output "redis_url" {
  description = "Redis cluster URL"
  value       = var.create_redis ? module.redis_response_store[0].url : null
}

output "redis_endpoint" {
  description = "Redis cluster endpoint"
  value       = var.create_redis ? module.redis_response_store[0].endpoint : null
}

# DynamoDB outputs
output "dynamodb_table_name" {
  description = "DynamoDB table name"
  value       = var.create_dynamodb ? module.dynamodb_response_store[0].table_name : null
}

output "dynamodb_table_arn" {
  description = "DynamoDB table ARN"
  value       = var.create_dynamodb ? module.dynamodb_response_store[0].table_arn : null
}