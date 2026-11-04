output "alb_security_group_id" {
  description = "Shared ALB security group ID"
  value       = aws_security_group.alb.id
}

output "ecs_service_security_group_id" {
  description = "Shared ECS service (REST service) security group ID"
  value       = aws_security_group.ecs_service.id
}

output "agent_runner_security_group_id" {
  description = "Shared Agent Runner security group ID (queue-mode examples only)"
  value       = aws_security_group.agent_runner.id
}
