# API Gateway Module Outputs

output "api_gateway_rest_api_id" {
  description = "ID of the API Gateway REST API"
  value       = aws_api_gateway_rest_api.rest_api.id
}

output "api_gateway_execution_arn" {
  description = "Execution ARN of the API Gateway REST API"
  value       = aws_api_gateway_rest_api.rest_api.execution_arn
}

output "api_gateway_stage_name" {
  description = "Name of the API Gateway stage"
  value       = aws_api_gateway_stage.stage.stage_name
}

output "api_gateway_stage_invoke_url" {
  description = "Invoke URL of the API Gateway stage"
  value       = aws_api_gateway_stage.stage.invoke_url
}

output "agent_invoke_url" {
  description = "Full invoke URL for the agent endpoint"
  value       = "${aws_api_gateway_stage.stage.invoke_url}/${var.api_base_path}/${var.api_version}/${var.agent_endpoint}"
}

output "api_gateway_deployment_id" {
  description = "ID of the API Gateway deployment"
  value       = aws_api_gateway_deployment.deployment.id
}

output "api_gateway_cloudwatch_log_group_arn" {
  description = "ARN of the CloudWatch log group for API Gateway"
  value       = aws_cloudwatch_log_group.api_gateway.arn
}

output "api_gateway_cloudwatch_log_group_name" {
  description = "Name of the CloudWatch log group for API Gateway"
  value       = aws_cloudwatch_log_group.api_gateway.name
}

output "api_gateway_authorizer_id" {
  description = "ID of the API Gateway authorizer (if created)"
  value       = var.create_authorizer ? aws_api_gateway_authorizer.lambda_authorizer[0].id : null
}
