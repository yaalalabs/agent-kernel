output "agent_runner_lambda_function_arn" {
  description = "ARN of the agent runner Lambda function"
  value       = module.agent_runner_lambda.lambda_function_arn
}

output "agent_runner_lambda_function_name" {
  description = "Name of the agent runner Lambda function"
  value       = module.agent_runner_lambda.lambda_function_name
}

output "agent_runner_lambda_function_invoke_arn" {
  description = "Invoke ARN of the agent runner Lambda function"
  value       = module.agent_runner_lambda.lambda_function_invoke_arn
}

output "agent_runner_event_source_mapping_uuid" {
  description = "UUID of the event source mapping"
  value       = aws_lambda_event_source_mapping.agent_runner_input_queue.uuid
}