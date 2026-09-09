output "agent_invoke_url" {
  description = "The URL to invoke the agent via API Gateway (use as AK_TEST_ENDPOINT)"
  value       = module.serverless_agents.agent_invoke_url
}

output "service_url" {
  description = "Direct Cloud Run service URL"
  value       = module.serverless_agents.service_url
}
