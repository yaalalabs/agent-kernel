output "websocket_api_endpoint_url" {
  description = "WebSocket API endpoint URL"
  value       = module.serverless_agents.websocket_api_endpoint_url
}

output "websocket_api_stage_name" {
  description = "WebSocket API stage name"
  value       = module.serverless_agents.websocket_api_stage_name
}
