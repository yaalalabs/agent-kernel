output "agent_invoke_url" {
  description = "The URL to invoke the agent Cloud Run service"
  value       = module.containerized_agents.agent_invoke_url
}
