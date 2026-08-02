output "websocket_api_endpoint_url" {
  description = "WebSocket API endpoint URL (wss://...)"
  value       = module.containerized_agents.websocket_api_endpoint_url
}

output "websocket_api_stage_name" {
  description = "WebSocket API stage name — append to the endpoint URL to connect"
  value       = module.containerized_agents.websocket_api_stage_name
}

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
