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

output "request_handler_security_group_id" {
  description = "Request handler security group ID used for the deployment (also used by the authorizer and WebSocket connection handler Lambdas)"
  value       = module.serverless_agents.request_handler_security_group_id
}

output "agent_runner_security_group_id" {
  description = "Agent runner security group ID used for the deployment"
  value       = module.serverless_agents.agent_runner_security_group_id
}

output "response_handler_security_group_id" {
  description = "Response handler security group ID used for the deployment"
  value       = module.serverless_agents.response_handler_security_group_id
}