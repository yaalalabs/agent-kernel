output "alb_dns_name" {
  value = module.rest_service.alb_dns_name
}

output "cluster_arn" {
  value = module.ecs.cluster_arn
}

output "api_gateway_id" {
  description = "HTTP API Gateway ID (REST/queue modes only; null in WebSocket modes)"
  value       = try(aws_apigatewayv2_api.http_api[0].id, null)
}

output "api_gateway_stage" {
  description = "HTTP API Gateway stage name (REST/queue modes only; null in WebSocket modes)"
  value       = try(aws_apigatewayv2_stage.stage[0].name, null)
}

output "api_gateway_cloudwatch_log_group_arn" {
  description = "ARN of the CloudWatch log group for API Gateway (null when access logging is disabled)"
  value       = var.enable_api_gateway_logs ? aws_cloudwatch_log_group.http_api[0].arn : null
}

output "api_gateway_cloudwatch_log_group_name" {
  description = "Name of the CloudWatch log group for API Gateway (null when access logging is disabled)"
  value       = var.enable_api_gateway_logs ? aws_cloudwatch_log_group.http_api[0].name : null
}

output "agent_invoke_url" {
  description = "HTTP agent invoke URL (REST/queue modes only; null in WebSocket modes)"
  value       = local.is_websocket_mode ? null : "${try(aws_apigatewayv2_stage.stage[0].invoke_url, format("%s/%s", aws_apigatewayv2_api.http_api[0].api_endpoint, aws_apigatewayv2_stage.stage[0].name))}/api/${var.api_version}/${var.agent_endpoint}"
}

output "vpc_id" {
  description = "VPC ID used for the deployment"
  value       = local.vpc_id
}

output "private_subnet_ids" {
  description = "Private subnet IDs used for the deployment"
  value       = local.subnet_ids
}

output "input_queue_url" {
  description = "URL of the SQS Input Queue (queue mode only)"
  value       = var.queue_mode ? module.queues[0].input_queue_url : null
}

output "output_queue_url" {
  description = "URL of the SQS Output Queue (queue mode only)"
  value       = var.queue_mode ? module.queues[0].output_queue_url : null
}

output "response_store_table_name" {
  description = "DynamoDB Response Store table name (REST queue modes only; null in WebSocket modes)"
  value       = (var.queue_mode && !local.is_websocket_mode) ? aws_dynamodb_table.response_store[0].name : null
}

output "agent_runner_service_name" {
  description = "ECS Agent Runner service name (queue mode only)"
  value       = var.queue_mode ? module.agent_runner[0].service_name : null
}

output "rest_service_image_uri" {
  description = "Docker image URI used by the REST Service ECS task"
  value       = module.docker_image[0].docker_image_uri
}

output "rest_service_name" {
  description = "ECS REST service name"
  value       = module.rest_service.service_name
}

output "rest_service_task_role_arn" {
  description = "ECS REST service task role ARN"
  value       = module.rest_service.task_role_arn
}

# WebSocket API outputs (async / stream modes only; null otherwise)

output "websocket_api_endpoint_url" {
  description = "WebSocket API endpoint URL (wss://...)"
  value       = try(aws_apigatewayv2_api.ws_api[0].api_endpoint, null)
}

output "websocket_api_id" {
  description = "WebSocket API ID"
  value       = try(aws_apigatewayv2_api.ws_api[0].id, null)
}

output "websocket_api_execution_arn" {
  description = "WebSocket API execution ARN"
  value       = try(aws_apigatewayv2_api.ws_api[0].execution_arn, null)
}

output "websocket_api_stage_name" {
  description = "WebSocket API stage name"
  value       = try(aws_apigatewayv2_stage.ws[0].name, null)
}

output "websocket_endpoint_url" {
  description = "WebSocket management endpoint URL used for PostToConnection"
  value       = local.is_websocket_mode ? "https://${aws_apigatewayv2_api.ws_api[0].id}.execute-api.${var.region}.amazonaws.com/${local.ws_stage_name}" : null
}

output "websocket_connection_table_name" {
  description = "DynamoDB WebSocket connections table name"
  value       = try(module.websocket_connections[0].table_name, null)
}

output "websocket_connection_table_arn" {
  description = "DynamoDB WebSocket connections table ARN"
  value       = try(module.websocket_connections[0].table_arn, null)
}

output "websocket_api_cloudwatch_log_group_arn" {
  description = "ARN of the CloudWatch log group for the WebSocket API Gateway (null when access logging is disabled)"
  value       = local.is_websocket_mode && var.enable_api_gateway_logs ? aws_cloudwatch_log_group.ws_api[0].arn : null
}

output "websocket_api_cloudwatch_log_group_name" {
  description = "Name of the CloudWatch log group for the WebSocket API Gateway (null when access logging is disabled)"
  value       = local.is_websocket_mode && var.enable_api_gateway_logs ? aws_cloudwatch_log_group.ws_api[0].name : null
}
