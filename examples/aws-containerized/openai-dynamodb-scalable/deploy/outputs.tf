output "agent_invoke_url" {
  description = "POST to this URL to chat with the agent (REST Sync queue mode)"
  value       = module.containerized_agents.agent_invoke_url
}

output "input_queue_url" {
  description = "SQS Input Queue URL"
  value       = module.containerized_agents.input_queue_url
}

output "output_queue_url" {
  description = "SQS Output Queue URL"
  value       = module.containerized_agents.output_queue_url
}

output "response_store_table_name" {
  description = "DynamoDB Response Store table name"
  value       = module.containerized_agents.response_store_table_name
}

output "agent_runner_service_name" {
  description = "ECS Agent Runner service name"
  value       = module.containerized_agents.agent_runner_service_name
}
