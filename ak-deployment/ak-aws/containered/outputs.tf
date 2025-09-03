output "alb_dns_name" {
  value = aws_lb.app.dns_name
}

output "cluster_arn" {
  value = module.ecs.cluster_arn
}

output "api_gateway_id" {
  value = aws_api_gateway_rest_api.rest_api.id
}

output "api_gateway_stage" {
  value = aws_api_gateway_stage.stage.stage_name
}

output "agent_invoke_url" {
  value = "${aws_api_gateway_stage.stage.invoke_url}${aws_api_gateway_resource.agent_endpoint.path}"
}
