output "agent_invoke_url" {
  description = "The URL to invoke the agent via API Gateway (use as AK_TEST_ENDPOINT)"
  value       = module.serverless_agents.agent_invoke_url
}

output "service_url" {
  description = "Direct Cloud Run service URL (use as AK_TEST_AUDIENCE)"
  value       = module.serverless_agents.service_url
}

output "authorizer_status" {
  description = "JWT authorizer configuration status"
  value       = module.serverless_agents.authorizer_status
}
