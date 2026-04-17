output "lambda_function_arn" {
  value = module.lambda_deployment.lambda_function_arn
}

output "lambda_function_name" {
  value = module.lambda_deployment.lambda_function_name
}

output "lambda_function_invoke_arn" {
  value = module.lambda_deployment.lambda_function_invoke_arn
}

output "lambda_role_arn" {
  value = aws_iam_role.lambda_role.arn
}

output "lambda_role_name" {
  description = "Name of the request handler Lambda execution role"
  value = aws_iam_role.lambda_role.name
}
