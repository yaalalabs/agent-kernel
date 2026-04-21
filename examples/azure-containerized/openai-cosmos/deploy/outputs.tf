output "api_url" {
  value = module.containerd_agent.api_management_gateway_url
  description = "API URL"
}

output "api_base_url" {
  value = module.containerd_agent.api_base_url
  description = "API Base URL" 
}

output "gateway_endpoints" {
  value = module.containerd_agent.gateway_endpoints
  description = "Gateway endpoints"
}

output "agent_invoke_url" {
  value = "${module.containerd_agent.api_base_url}/chat"
}