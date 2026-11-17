output "api_base_url" {
  value       = module.containerd_agent.api_base_url
  description = "API Base URL"
}

output "agent_invoke_url" {
  value = "${module.containerd_agent.api_base_url}/chat"
}

output "servicebus_namespace" {
  description = "Service Bus namespace FQDN; the weekly test exports it as AK_TEST_SERVICEBUS_NAMESPACE"
  value       = module.containerd_agent.servicebus_namespace
}

output "vnet_id" {
  description = "ID of the Virtual Network"
  value       = module.containerd_agent.vnet_id
}

output "subnet_ids" {
  description = "IDs of the subnets"
  value       = module.containerd_agent.private_subnet_ids
}
