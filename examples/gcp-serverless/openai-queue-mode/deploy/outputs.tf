output "agent_invoke_url" {
  description = "The URL to invoke the agent through API Gateway"
  value       = module.serverless_agents.agent_invoke_url
}

output "input_topic" {
  description = "Pub/Sub topic carrying chat requests"
  value       = module.serverless_agents.input_topic
}

output "agent_runner_service" {
  description = "The agent-runner Cloud Run service"
  value       = module.serverless_agents.agent_runner_service
}
