output "lambda_function_arn" {
  value = module.request_handler.lambda_function_arn
}

output "lambda_function_name" {
  value = module.request_handler.lambda_function_name
}

output "lambda_function_invoke_arn" {
  value = module.request_handler.lambda_function_invoke_arn
}

output "lambda_role_arn" {
  description = "ARN of the request-handler Lambda execution role"
  value       = module.request_handler.lambda_role_arn
}

output "authorizer_status" {
  description = "Status message indicating whether the authorizer Lambda will be created"
  value       = local.authorizer_status_message
}

output "agent_invoke_url" {
  description = "Invoke URL for the agent chat endpoint"
  value = "${aws_api_gateway_stage.stage.invoke_url}/${var.api_base_path}/${var.api_version}/${var.agent_endpoint}"
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
  value       = module.api_gateway[0].api_gateway_rest_api_id
}

output "api_gateway_stage_name" {
  description = "API Gateway stage name"
  value       = module.api_gateway[0].api_gateway_stage_name
}

output "api_gateway_execution_arn" {
  description = "Execution ARN of the API Gateway REST API"
  value       = module.api_gateway[0].api_gateway_execution_arn
}

output "api_gateway_cloudwatch_log_group_arn" {
  description = "ARN of the CloudWatch log group for API Gateway"
  value       = module.api_gateway[0].api_gateway_cloudwatch_log_group_arn
}

output "api_gateway_cloudwatch_log_group_name" {
  description = "Name of the CloudWatch log group for API Gateway"
  value       = module.api_gateway[0].api_gateway_cloudwatch_log_group_name
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

# SQS Queues outputs (conditional based on queue_mode)
output "input_queue_arn" {
  description = "ARN of the input SQS queue"
  value       = var.queue_mode ? module.queues[0].input_queue_arn : null
}

output "input_queue_url" {
  description = "URL of the input SQS queue"
  value       = var.queue_mode ? module.queues[0].input_queue_url : null
}

output "input_queue_name" {
  description = "Name of the input SQS queue"
  value       = var.queue_mode ? module.queues[0].input_queue_name : null
}

output "output_queue_arn" {
  description = "ARN of the output SQS queue"
  value       = var.queue_mode ? module.queues[0].output_queue_arn : null
}

output "output_queue_url" {
  description = "URL of the output SQS queue"
  value       = var.queue_mode ? module.queues[0].output_queue_url : null
}

output "output_queue_name" {
  description = "Name of the output SQS queue"
  value       = var.queue_mode ? module.queues[0].output_queue_name : null
}

