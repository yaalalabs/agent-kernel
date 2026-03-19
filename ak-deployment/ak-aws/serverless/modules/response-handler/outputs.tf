# Outputs for the response handler module
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