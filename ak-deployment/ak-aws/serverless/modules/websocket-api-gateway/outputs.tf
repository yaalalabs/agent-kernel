# WebSocket API Gateway Module Outputs

output "websocket_api_id" {
  description = "ID of the WebSocket API"
  value       = aws_apigatewayv2_api.websocket_api.id
}

output "websocket_api_endpoint" {
  description = "WebSocket API endpoint URL"
  value       = aws_apigatewayv2_api.websocket_api.api_endpoint
}

output "websocket_stage_name" {
  description = "Name of the WebSocket API stage"
  value       = aws_apigatewayv2_stage.websocket_stage.name
}

output "websocket_stage_invoke_url" {
  description = "Invoke URL of the WebSocket API stage"
  value       = aws_apigatewayv2_stage.websocket_stage.invoke_url
}

output "websocket_api_execution_arn" {
  description = "Execution ARN of the WebSocket API"
  value       = aws_apigatewayv2_api.websocket_api.execution_arn
}

output "websocket_cloudwatch_log_group_arn" {
  description = "ARN of the CloudWatch log group for WebSocket API"
  value       = aws_cloudwatch_log_group.websocket_api.arn
}

output "websocket_cloudwatch_log_group_name" {
  description = "Name of the CloudWatch log group for WebSocket API"
  value       = aws_cloudwatch_log_group.websocket_api.name
}