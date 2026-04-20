output "agent_invoke_url" {
  description = "The URL to invoke the agent Cloud Run service"
  value       = module.serverless_agents.agent_invoke_url
}
