output "agent_invoke_url" {
  description = "The URL to invoke the agent ECS container"
  value       = module.containerized_agents.agent_invoke_url
}