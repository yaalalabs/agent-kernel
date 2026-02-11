output "lambda_function_name" {
  description = "Name of the authorizer Lambda function"
  value       = module.authorizer_lambda_deployment.lambda_function_name
}

output "lambda_function_arn" {
  description = "ARN of the authorizer Lambda function"
  value       = module.authorizer_lambda_deployment.lambda_function_arn
}

output "lambda_function_invoke_arn" {
  description = "Invoke ARN of the authorizer Lambda function"
  value       = module.authorizer_lambda_deployment.lambda_function_invoke_arn
}

output "lambda_role_arn" {
  description = "ARN of the authorizer Lambda IAM role"
  value       = aws_iam_role.authorizer_lambda_role.arn
}

output "lambda_security_group_id" {
  description = "ID of the authorizer Lambda security group (if created)"
  value       = length(aws_security_group.authorizer_lambda) > 0 ? aws_security_group.authorizer_lambda[0].id : null
}