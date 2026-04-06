output "agent_invoke_url" {
  description = "The URL to invoke the agent Cloud Function"
  value       = module.serverless_agents.agent_invoke_url
}
