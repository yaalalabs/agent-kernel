output "lambda_function_arn" {
  value = module.lambda_deployment.lambda_function_arn
}

output "lambda_function_name" {
  value = module.lambda_deployment.lambda_function_name
}

output "lambda_function_invoke_arn" {
  value = module.lambda_deployment.lambda_function_invoke_arn
}

output "agent_invoke_url" {
  value = "${aws_api_gateway_stage.stage.invoke_url}/${var.api_base_path}/${var.api_version}/${var.agent_endpoint}"
}
