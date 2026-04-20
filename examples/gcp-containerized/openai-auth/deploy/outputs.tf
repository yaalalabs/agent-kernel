output "agent_invoke_url" {
  description = "The URL to invoke the agent via API Gateway"
  value       = module.containerized_agents.agent_invoke_url
}

output "service_url" {
  description = "Direct Cloud Run service URL"
  value       = module.containerized_agents.service_url
}

output "authorizer_status" {
  description = "JWT authorizer configuration status"
  value       = module.containerized_agents.authorizer_status
}
