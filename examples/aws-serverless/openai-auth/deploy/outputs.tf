output "authorizer_status" {
  description = "Status message indicating whether the authorizer Lambda will be created"
  value       = module.serverless_agents.authorizer_status
}

output "agent_invoke_url" {
  description = "The URL to invoke the agent lambda function"
  value       = module.serverless_agents.agent_invoke_url
}