# WebSocket API Gateway Module Outputs

output "websocket_api_endpoint_url" {
  description = "WebSocket API endpoint URL"
  value       = module.websocket_api.api_endpoint
}

output "websocket_api_id" {
  description = "WebSocket API ID"
  value       = module.websocket_api.api_id
}

output "websocket_api_execution_arn" {
  description = "WebSocket API execution ARN"
  value       = module.websocket_api.api_execution_arn
}

output "websocket_api_stage_name" {
  description = "WebSocket API stage name"
  value       = module.websocket_api.stage_names[0]
}

output "websocket_api_stage_arn" {
  description = "WebSocket API stage ARN"
  value       = module.websocket_api.stage_arns[0]
}

output "websocket_connection_table_name" {
  description = "DynamoDB table name for WebSocket connection mapping"
  value       = module.websocket_connections.table_name
}

output "websocket_connection_table_arn" {
  description = "DynamoDB table ARN for WebSocket connection mapping"
  value       = module.websocket_connections.table_arn
}

output "websocket_connection_table_gsi_name" {
  description = "Global Secondary Index name for connection_id lookups"
  value       = "connection_id-index"
}

output "websocket_cloudwatch_log_group_arn" {
  description = "ARN of the CloudWatch log group for WebSocket API"
  value       = module.websocket_api.stage_log_group_arns[0]
}

output "websocket_cloudwatch_log_group_name" {
  description = "Name of the CloudWatch log group for WebSocket API"
  value       = module.websocket_api.stage_log_group_names[0]
}
