# WebSocket Connections Table Module Outputs

output "table_name" {
  description = "Name of the WebSocket connections DynamoDB table"
  value       = aws_dynamodb_table.websocket_connections.name
}

output "table_arn" {
  description = "ARN of the WebSocket connections DynamoDB table"
  value       = aws_dynamodb_table.websocket_connections.arn
}

output "table_id" {
  description = "ID of the WebSocket connections DynamoDB table"
  value       = aws_dynamodb_table.websocket_connections.id
}