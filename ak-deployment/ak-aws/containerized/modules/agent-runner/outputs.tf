output "service_name" {
  description = "Agent Runner ECS service name"
  value       = aws_ecs_service.agent_runner.name
}

output "service_arn" {
  description = "Agent Runner ECS service ARN"
  value       = aws_ecs_service.agent_runner.arn
}

output "task_role_arn" {
  description = "Agent Runner task role ARN"
  value       = aws_iam_role.agent_runner_task_role.arn
}

output "execution_role_arn" {
  description = "Agent Runner execution role ARN"
  value       = aws_iam_role.agent_runner_execution_role.arn
}

output "security_group_id" {
  description = "Agent Runner security group ID"
  value       = aws_security_group.agent_runner.id
}
