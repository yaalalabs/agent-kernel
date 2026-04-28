output "agent_invoke_url" {
  description = "The URL to invoke the agent lambda function"
  value       = module.serverless_agents.agent_invoke_url
}

output "vpc_id" {
  description = "VPC ID used for the deployment"
  value       = module.serverless_agents.vpc_id
}

output "private_subnet_ids" {
  description = "Private subnet IDs used for the deployment"
  value       = module.serverless_agents.private_subnet_ids
}