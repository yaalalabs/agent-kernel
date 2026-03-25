output "lambda_function_arn" {
  value = module.request_handler.lambda_function_arn
}

output "lambda_function_name" {
  value = module.request_handler.lambda_function_name
}

output "lambda_function_invoke_arn" {
  value = module.request_handler.lambda_function_invoke_arn
}

output "authorizer_status" {
  description = "Status message indicating whether the authorizer Lambda will be created"
  value       = local.authorizer_status_message
}

output "agent_invoke_url" {
  description = "Invoke URL for the agent chat endpoint"
  value       = local.agent_invoke_url
}

output "api_gateway_id" {
  description = "API Gateway REST API ID"
  value       = local.is_async_mode ? null : module.api_gateway[0].api_gateway_rest_api_id
}

output "api_gateway_stage_name" {
  description = "API Gateway stage name"
  value       = local.is_async_mode ? null : module.api_gateway[0].api_gateway_stage_name
}

output "api_gateway_execution_arn" {
  description = "Execution ARN of the API Gateway REST API"
  value       = local.is_async_mode ? null : module.api_gateway[0].api_gateway_execution_arn
}

output "api_gateway_cloudwatch_log_group_arn" {
  description = "ARN of the CloudWatch log group for API Gateway"
  value       = local.is_async_mode ? null : module.api_gateway[0].api_gateway_cloudwatch_log_group_arn
}

output "api_gateway_cloudwatch_log_group_name" {
  description = "Name of the CloudWatch log group for API Gateway"
  value       = local.is_async_mode ? null : module.api_gateway[0].api_gateway_cloudwatch_log_group_name
}

# Response Handler outputs (conditional based on scalable_mode)
output "response_handler_lambda_function_arn" {
  description = "ARN of the response handler Lambda function"
  value       = var.scalable_mode ? module.response_handler[0].response_handler_lambda_function_arn : null
}

output "response_handler_lambda_function_name" {
  description = "Name of the response handler Lambda function"
  value       = var.scalable_mode ? module.response_handler[0].response_handler_lambda_function_name : null
}

output "response_handler_lambda_function_invoke_arn" {
  description = "Invoke ARN of the response handler Lambda function"
  value       = var.scalable_mode ? module.response_handler[0].response_handler_lambda_function_invoke_arn : null
}

# Agent Runner outputs (conditional based on scalable_mode)
output "agent_runner_lambda_function_arn" {
  description = "ARN of the agent runner Lambda function"
  value       = var.scalable_mode ? module.agent_runner[0].agent_runner_lambda_function_arn : null
}

output "agent_runner_lambda_function_name" {
  description = "Name of the agent runner Lambda function"
  value       = var.scalable_mode ? module.agent_runner[0].agent_runner_lambda_function_name : null
}

output "agent_runner_lambda_function_invoke_arn" {
  description = "Invoke ARN of the agent runner Lambda function"
  value       = var.scalable_mode ? module.agent_runner[0].agent_runner_lambda_function_invoke_arn : null
}

# SQS Queues outputs (conditional based on scalable_mode)
output "input_queue_arn" {
  description = "ARN of the input SQS queue"
  value       = var.scalable_mode ? module.queues[0].input_queue_arn : null
}

output "input_queue_url" {
  description = "URL of the input SQS queue"
  value       = var.scalable_mode ? module.queues[0].input_queue_url : null
}

output "input_queue_name" {
  description = "Name of the input SQS queue"
  value       = var.scalable_mode ? module.queues[0].input_queue_name : null
}

output "output_queue_arn" {
  description = "ARN of the output SQS queue"
  value       = var.scalable_mode ? module.queues[0].output_queue_arn : null
}

output "output_queue_url" {
  description = "URL of the output SQS queue"
  value       = var.scalable_mode ? module.queues[0].output_queue_url : null
}

output "output_queue_name" {
  description = "Name of the output SQS queue"
  value       = var.scalable_mode ? module.queues[0].output_queue_name : null
}

# Database outputs (conditional based on scalable_mode and execution_mode)
output "redis_response_store_url" {
  description = "URL of the Redis response store"
  value       = local.create_response_store ? module.response_stores[0].redis_url : null
}

output "dynamodb_response_store_table_name" {
  description = "Name of the DynamoDB response store table"
  value       = local.create_response_store ? module.response_stores[0].dynamodb_table_name : null
}

output "dynamodb_response_store_table_arn" {
  description = "ARN of the DynamoDB response store table"
  value       = local.create_response_store ? module.response_stores[0].dynamodb_table_arn : null
}

# WebSocket API Gateway outputs (conditional based on async execution mode)
output "websocket_api_id" {
  description = "ID of the WebSocket API"
  value       = local.is_async_mode ? module.websocket_api_gateway[0].websocket_api_id : null
}

output "websocket_api_endpoint" {
  description = "WebSocket API endpoint URL"
  value       = local.is_async_mode ? module.websocket_api_gateway[0].websocket_api_endpoint : null
}

output "websocket_stage_invoke_url" {
  description = "Invoke URL of the WebSocket API stage"
  value       = local.is_async_mode ? module.websocket_api_gateway[0].websocket_stage_invoke_url : null
}

output "websocket_connections_table_name" {
  description = "Name of the WebSocket connections DynamoDB table"
  value       = local.is_async_mode ? module.websocket_connections_table[0].table_name : null
}

output "websocket_connections_table_arn" {
  description = "ARN of the WebSocket connections DynamoDB table"
  value       = local.is_async_mode ? module.websocket_connections_table[0].table_arn : null
}