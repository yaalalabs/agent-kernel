output "request_handler_lambda_function_name" {
  value = local.request_handler_lambda_function_name
}

output "request_handler_lambda_function_arn" {
  value = local.request_handler_enabled ? module.request_handler[0].lambda_function_arn : null
}

output "request_handler_lambda_function_invoke_arn" {
  value = local.request_handler_lambda_invoke_arn
}

output "request_handler_lambda_role_arn" {
  description = "ARN of the request-handler Lambda execution role"
  value       = local.request_handler_enabled ? module.request_handler[0].lambda_role_arn : null
}

output "request_handler_lambda_role_name" {
  description = "Name of the request-handler Lambda execution role"
  value       = local.request_handler_enabled ? module.request_handler[0].lambda_role_name : null
}

output "authorizer_status" {
  description = "Status message indicating whether the authorizer Lambda will be created"
  value       = local.authorizer_status_message
}

output "agent_invoke_url" {
  description = "Invoke URL for the agent chat endpoint"
  value       = try(module.api_gateway[0].agent_invoke_url, null)
}

output "vpc_id" {
  description = "VPC ID used for the deployment"
  value       = local.vpc_id
}

output "private_subnet_ids" {
  description = "Private subnet IDs used for the deployment"
  value       = local.subnet_ids
}

output "api_gateway_id" {
  description = "API Gateway REST API ID"
  value       = try(module.api_gateway[0].api_gateway_rest_api_id, null)
}

output "api_gateway_stage_name" {
  description = "API Gateway stage name"
  value       = try(module.api_gateway[0].api_gateway_stage_name, null)
}

output "api_gateway_execution_arn" {
  description = "Execution ARN of the API Gateway REST API"
  value       = try(module.api_gateway[0].api_gateway_execution_arn, null)
}

output "api_gateway_cloudwatch_log_group_arn" {
  description = "ARN of the CloudWatch log group for API Gateway"
  value       = try(module.api_gateway[0].api_gateway_cloudwatch_log_group_arn, null)
}

output "api_gateway_cloudwatch_log_group_name" {
  description = "Name of the CloudWatch log group for API Gateway"
  value       = try(module.api_gateway[0].api_gateway_cloudwatch_log_group_name, null)
}

# Response Handler outputs (conditional based on queue_mode)
output "response_handler_lambda_function_arn" {
  description = "ARN of the response handler Lambda function"
  value       = var.queue_mode ? module.response_handler[0].response_handler_lambda_function_arn : null
}

output "response_handler_lambda_function_name" {
  description = "Name of the response handler Lambda function"
  value       = var.queue_mode ? module.response_handler[0].response_handler_lambda_function_name : null
}

output "response_handler_lambda_function_invoke_arn" {
  description = "Invoke ARN of the response handler Lambda function"
  value       = var.queue_mode ? module.response_handler[0].response_handler_lambda_function_invoke_arn : null
}

output "response_handler_lambda_role_arn" {
  description = "ARN of the response handler Lambda execution role"
  value       = var.queue_mode ? module.response_handler[0].response_handler_lambda_role_arn : null
}

output "response_handler_lambda_role_name" {
  description = "Name of the response handler Lambda execution role"
  value       = var.queue_mode ? module.response_handler[0].response_handler_lambda_role_name : null
}

# Agent Runner outputs (conditional based on queue_mode)
output "agent_runner_lambda_function_arn" {
  description = "ARN of the agent runner Lambda function"
  value       = var.queue_mode ? module.agent_runner[0].agent_runner_lambda_function_arn : null
}

output "agent_runner_lambda_function_name" {
  description = "Name of the agent runner Lambda function"
  value       = var.queue_mode ? module.agent_runner[0].agent_runner_lambda_function_name : null
}

output "agent_runner_lambda_function_invoke_arn" {
  description = "Invoke ARN of the agent runner Lambda function"
  value       = var.queue_mode ? module.agent_runner[0].agent_runner_lambda_function_invoke_arn : null
}

output "agent_runner_lambda_role_arn" {
  description = "ARN of the agent runner Lambda execution role"
  value       = var.queue_mode ? module.agent_runner[0].agent_runner_lambda_role_arn : null
}

output "agent_runner_lambda_role_name" {
  description = "Name of the agent runner Lambda execution role"
  value       = var.queue_mode ? module.agent_runner[0].agent_runner_lambda_role_name : null
}

# SQS Queues outputs (conditional based on queue_mode)
output "input_queue_arn" {
  description = "ARN of the input SQS queue"
  value       = local.input_queue_arn
}

output "input_queue_url" {
  description = "URL of the input SQS queue"
  value       = local.input_queue_url
}

output "input_queue_name" {
  description = "Name of the input SQS queue"
  value       = var.queue_mode ? module.queues[0].input_queue_name : null
}

output "input_dlq_arn" {
  description = "ARN of the input SQS dead-letter queue"
  value       = var.queue_mode ? module.queues[0].input_dlq_arn : null
}

output "input_dlq_url" {
  description = "URL of the input SQS dead-letter queue"
  value       = var.queue_mode ? module.queues[0].input_dlq_url : null
}

output "output_queue_arn" {
  description = "ARN of the output SQS queue"
  value       = local.output_queue_arn
}

output "output_queue_url" {
  description = "URL of the output SQS queue"
  value       = local.output_queue_url
}

output "output_queue_name" {
  description = "Name of the output SQS queue"
  value       = var.queue_mode ? module.queues[0].output_queue_name : null
}

output "output_dlq_arn" {
  description = "ARN of the output SQS dead-letter queue"
  value       = var.queue_mode ? module.queues[0].output_dlq_arn : null
}

output "output_dlq_url" {
  description = "URL of the output SQS dead-letter queue"
  value       = var.queue_mode ? module.queues[0].output_dlq_url : null
}

# WebSocket API Gateway outputs (conditional based on execution_mode == "async")
output "websocket_api_endpoint_url" {
  description = "WebSocket API endpoint URL"
  value       = try(module.websocket_api_gateway[0].websocket_api_endpoint_url, null)
}

output "websocket_api_id" {
  description = "WebSocket API ID"
  value       = try(module.websocket_api_gateway[0].websocket_api_id, null)
}

output "websocket_api_execution_arn" {
  description = "WebSocket API execution ARN"
  value       = try(module.websocket_api_gateway[0].websocket_api_execution_arn, null)
}

output "websocket_api_stage_name" {
  description = "WebSocket API stage name"
  value       = try(module.websocket_api_gateway[0].websocket_api_stage_name, null)
}

output "websocket_api_stage_arn" {
  description = "WebSocket API stage ARN"
  value       = try(module.websocket_api_gateway[0].websocket_api_stage_arn, null)
}

output "websocket_connection_table_name" {
  description = "DynamoDB table name for WebSocket connection mapping"
  value       = local.websocket_connection_table_name
}

output "websocket_connection_table_arn" {
  description = "DynamoDB table ARN for WebSocket connection mapping"
  value       = local.websocket_connection_table_arn
}

output "websocket_cloudwatch_log_group_arn" {
  description = "ARN of the CloudWatch log group for WebSocket API"
  value       = try(module.websocket_api_gateway[0].websocket_cloudwatch_log_group_arn, null)
}

output "websocket_cloudwatch_log_group_name" {
  description = "Name of the CloudWatch log group for WebSocket API"
  value       = try(module.websocket_api_gateway[0].websocket_cloudwatch_log_group_name, null)
}

# WebSocket Connection Handler outputs (conditional based on execution_mode == "async")
output "ws_connection_handler_lambda_function_arn" {
  description = "ARN of the WebSocket connection handler Lambda function"
  value       = try(module.ws_connection_handler[0].ws_connection_handler_lambda_function_arn, null)
}

output "ws_connection_handler_lambda_function_name" {
  description = "Name of the WebSocket connection handler Lambda function"
  value       = try(module.ws_connection_handler[0].ws_connection_handler_lambda_function_name, null)
}

output "ws_connection_handler_lambda_function_invoke_arn" {
  description = "Invoke ARN of the WebSocket connection handler Lambda function"
  value       = try(module.ws_connection_handler[0].ws_connection_handler_lambda_function_invoke_arn, null)
}

output "ws_connection_handler_lambda_role_arn" {
  description = "ARN of the WebSocket connection handler Lambda execution role"
  value       = try(module.ws_connection_handler[0].ws_connection_handler_lambda_role_arn, null)
}

output "ws_connection_handler_lambda_role_name" {
  description = "Name of the WebSocket connection handler Lambda execution role"
  value       = try(module.ws_connection_handler[0].ws_connection_handler_lambda_role_name, null)
}
