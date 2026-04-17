output "response_handler_lambda_function_arn" {
  description = "ARN of the response handler Lambda function"
  value       = module.response_handler_lambda.lambda_function_arn
}

output "response_handler_lambda_function_name" {
  description = "Name of the response handler Lambda function"
  value       = module.response_handler_lambda.lambda_function_name
}

output "response_handler_lambda_function_invoke_arn" {
  description = "Invoke ARN of the response handler Lambda function"
  value       = module.response_handler_lambda.lambda_function_invoke_arn
}

output "response_handler_lambda_role_arn" {
  description = "ARN of the response handler Lambda execution role"
  value       = module.response_handler_lambda.lambda_role_arn
}

output "response_handler_lambda_role_name" {
  description = "Name of the response handler Lambda execution role"
  value       = aws_iam_role.response_handler_lambda_role.name
}

output "response_handler_event_source_mapping_uuid" {
  description = "UUID of the event source mapping"
  value       = aws_lambda_event_source_mapping.response_handler_output_queue.uuid
}