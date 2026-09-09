output "agent_invoke_url" {
  description = "POST to this URL to chat with the agent, with or without a `schedule` block"
  value       = module.serverless_agents.agent_invoke_url
}

# Scheduling resources (null unless the matching flag is set)

output "schedule_group_name" {
  description = "EventBridge Scheduler schedule-group name each task registers its schedule in"
  value       = module.serverless_agents.schedule_group_name
}

output "schedule_group_arn" {
  description = "EventBridge Scheduler schedule-group ARN"
  value       = module.serverless_agents.schedule_group_arn
}

output "scheduler_execution_role_arn" {
  description = "Role EventBridge Scheduler assumes to deliver triggers to the Input Queue"
  value       = module.serverless_agents.scheduler_execution_role_arn
}

output "schedule_table_name" {
  description = "DynamoDB schedule store table name"
  value       = module.serverless_agents.schedule_table_name
}
