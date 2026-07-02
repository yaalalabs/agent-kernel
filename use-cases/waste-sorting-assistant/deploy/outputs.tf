output "agent_invoke_url" {
  description = "URL for invoking the deployed Agent Kernel API."
  value       = module.serverless_agents.agent_invoke_url
}

output "vpc_id" {
  description = "VPC ID used by the Agent Kernel deployment."
  value       = module.serverless_agents.vpc_id
}

output "private_subnet_ids" {
  description = "Private subnet IDs used by the Agent Kernel deployment."
  value       = module.serverless_agents.private_subnet_ids
}
