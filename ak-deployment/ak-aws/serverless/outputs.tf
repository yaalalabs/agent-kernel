output "lambda_function_arn" {
  value = module.lambda_deployment.lambda_function_arn
}

output "lambda_function_name" {
  value = module.lambda_deployment.lambda_function_name
}

output "lambda_function_invoke_arn" {
  value = module.lambda_deployment.lambda_function_invoke_arn
}

output "authorizer_status" {
  description = "Status message indicating whether the authorizer Lambda will be created"
  value       = local.authorizer_status_message
}

output "agent_invoke_url" {
  value = "${aws_api_gateway_stage.stage.invoke_url}/${var.api_base_path}/${var.api_version}/${var.agent_endpoint}"
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