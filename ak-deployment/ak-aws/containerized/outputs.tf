output "alb_dns_name" {
  value = module.rest_service.alb_dns_name
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

output "input_queue_url" {
  description = "URL of the SQS Input Queue (queue mode only)"
  value       = var.enable_queue_mode ? module.queues[0].input_queue_url : null
}

output "output_queue_url" {
  description = "URL of the SQS Output Queue (queue mode only)"
  value       = var.enable_queue_mode ? module.queues[0].output_queue_url : null
}

output "response_store_table_name" {
  description = "DynamoDB Response Store table name (queue mode only)"
  value       = var.enable_queue_mode ? aws_dynamodb_table.response_store[0].name : null
}

output "agent_runner_service_name" {
  description = "ECS Agent Runner service name (queue mode only)"
  value       = var.enable_queue_mode ? module.agent_runner[0].service_name : null
}

output "rest_service_image_uri" {
  description = "Docker image URI used by the REST Service ECS task"
  value       = module.docker_image[0].docker_image_uri
}

output "rest_service_name" {
  description = "ECS REST service name"
  value       = module.rest_service.service_name
}

output "rest_service_task_role_arn" {
  description = "ECS REST service task role ARN"
  value       = module.rest_service.task_role_arn
}
