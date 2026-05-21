output "ws_connection_handler_lambda_function_arn" {
  description = "ARN of the WebSocket connection handler Lambda function"
  value       = module.ws_connection_handler_lambda.lambda_function_arn
}

output "ws_connection_handler_lambda_function_name" {
  description = "Name of the WebSocket connection handler Lambda function"
  value       = module.ws_connection_handler_lambda.lambda_function_name
}

output "ws_connection_handler_lambda_function_invoke_arn" {
  description = "Invoke ARN of the WebSocket connection handler Lambda function"
  value       = module.ws_connection_handler_lambda.lambda_function_invoke_arn
}

output "ws_connection_handler_lambda_role_arn" {
  description = "ARN of the WebSocket connection handler Lambda execution role"
  value       = aws_iam_role.ws_connection_handler_lambda_role.arn
}

output "ws_connection_handler_lambda_role_name" {
  description = "Name of the WebSocket connection handler Lambda execution role"
  value       = aws_iam_role.ws_connection_handler_lambda_role.name
}
