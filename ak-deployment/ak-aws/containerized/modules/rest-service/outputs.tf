output "service_arn" {
  description = "ECS service ARN"
  value       = module.ecs_service.services[var.service_name].service_arn
}

output "service_name" {
  description = "ECS service name"
  value       = module.ecs_service.services[var.service_name].service_name
}

output "task_role_name" {
  description = "ECS task role name"
  value       = module.ecs_service.services[var.service_name].tasks_iam_role_name
}

output "task_role_arn" {
  description = "ECS task role ARN"
  value       = module.ecs_service.services[var.service_name].tasks_iam_role_arn
}

output "alb_arn" {
  description = "Application Load Balancer ARN"
  value       = aws_lb.app.arn
}

output "alb_dns_name" {
  description = "Application Load Balancer DNS name"
  value       = aws_lb.app.dns_name
}

output "alb_listener_arn" {
  description = "ALB HTTP listener ARN"
  value       = aws_lb_listener.http.arn
}

output "target_group_arn" {
  description = "ALB target group ARN"
  value       = aws_lb_target_group.app.arn
}

output "security_group_id" {
  description = "ECS service security group ID"
  value       = aws_security_group.ecs_service.id
}

output "alb_security_group_id" {
  description = "ALB security group ID"
  value       = aws_security_group.ecs_alb.id
}
