output "websocket_api_endpoint_url" {
  description = "WebSocket API endpoint URL (wss://...)"
  value       = module.containerized_agents.websocket_api_endpoint_url
}

output "websocket_api_stage_name" {
  description = "WebSocket API stage name — append to the endpoint URL to connect"
  value       = module.containerized_agents.websocket_api_stage_name
}
