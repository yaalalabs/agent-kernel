output "agent_invoke_url" {
  description = "The URL to invoke the agent lambda function"
  value       = module.serverless_agents.agent_invoke_url
}

output "authorizer_status" {
  description = "Status of the API Gateway Authorizer"
  value       = module.serverless_agents.authorizer_status
}