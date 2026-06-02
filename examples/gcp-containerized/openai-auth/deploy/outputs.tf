output "agent_invoke_url" {
  description = "The URL to invoke the agent via API Gateway (use as AK_TEST_ENDPOINT)"
  value       = module.containerized_agents.agent_invoke_url
}

output "gateway_url" {
  description = "API Gateway base URL"
  value       = "https://${module.containerized_agents.gateway_url}"
}

output "service_url" {
  description = "Direct Cloud Run service URL (use as AK_TEST_AUDIENCE)"
  value       = module.containerized_agents.service_url
}

output "authorizer_status" {
  description = "JWT authorizer configuration status"
  value       = module.containerized_agents.authorizer_status
}
