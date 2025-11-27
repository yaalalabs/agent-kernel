output "table_name" {
  description = "DynamoDB table name"
  value       = module.dynamodb_table.dynamodb_table_id
}

output "table_arn" {
  description = "DynamoDB table ARN"
  value       = module.dynamodb_table.dynamodb_table_arn
}

output "table_id" {
  description = "DynamoDB table ID"
  value       = module.dynamodb_table.dynamodb_table_id
}

output "stream_arn" {
  description = "DynamoDB stream ARN (if enabled)"
  value       = try(module.dynamodb_table.dynamodb_table_stream_arn, null)
}

output "stream_label" {
  description = "DynamoDB stream label (if enabled)"
  value       = try(module.dynamodb_table.dynamodb_table_stream_label, null)
}
