output "input_queue_url" {
  description = "SQS Input Queue URL"
  value       = module.containerized_agents.input_queue_url
}

output "output_queue_url" {
  description = "SQS Output Queue URL"
  value       = module.containerized_agents.output_queue_url
}

output "agent_runner_service_name" {
  description = "ECS Agent Runner service name"
  value       = module.containerized_agents.agent_runner_service_name
}

output "rest_service_name" {
  description = "ECS IO Service name (LiveKit Gateway)"
  value       = module.containerized_agents.rest_service_name
}
