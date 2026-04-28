output "alb_dns_name" {
  value = aws_lb.app.dns_name
}

output "cluster_arn" {
  value = module.ecs.cluster_arn
}

output "api_gateway_id" {
  value = aws_apigatewayv2_api.http_api.id
}

output "api_gateway_stage" {
  value = aws_apigatewayv2_stage.stage.name
}

output "agent_invoke_url" {
  value = "${try(aws_apigatewayv2_stage.stage.invoke_url, format("%s/%s", aws_apigatewayv2_api.http_api.api_endpoint, aws_apigatewayv2_stage.stage.name))}/api/${var.api_version}/${var.agent_endpoint}"
}

output "vpc_id" {
  description = "VPC ID used for the deployment"
  value       = local.vpc_id
}

output "private_subnet_ids" {
  description = "Private subnet IDs used for the deployment"
  value       = local.subnet_ids
}
