output "api_gateway_url" {
  description = "API Gateway URL"
  value       = module.containered_agents.api_gateway_url
}

output "ecs_cluster_name" {
  description = "ECS Cluster Name"
  value       = module.containered_agents.ecs_cluster_name
}

output "ecs_service_name" {
  description = "ECS Service Name"
  value       = module.containered_agents.ecs_service_name
}
