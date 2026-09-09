output "agent_invoke_url" {
  description = "POST to this URL to chat with the agent, with or without a `schedule` block"
  value       = module.containerized_agents.agent_invoke_url
}

output "input_queue_url" {
  description = "SQS Input Queue URL — EventBridge Scheduler delivers each occurrence here"
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

# Scheduling resources

output "schedule_group_name" {
  description = "EventBridge Scheduler schedule-group name each task registers its schedule in"
  value       = module.containerized_agents.schedule_group_name
}

output "schedule_group_arn" {
  description = "EventBridge Scheduler schedule-group ARN"
  value       = module.containerized_agents.schedule_group_arn
}

output "scheduler_execution_role_arn" {
  description = "Role EventBridge Scheduler assumes to deliver triggers to the Input Queue"
  value       = module.containerized_agents.scheduler_execution_role_arn
}

output "schedule_table_name" {
  description = "DynamoDB schedule store table name"
  value       = module.containerized_agents.schedule_table_name
}
