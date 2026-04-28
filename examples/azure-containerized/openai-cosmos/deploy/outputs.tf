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
output "vnet_id" {
  description = "ID of the Virtual Network"
  value       = module.containerd_agent.vnet_id
  
}

output "subnet_ids" {
  description = "IDs of the subnets"
  value       = module.containerd_agent.private_subnet_ids
}