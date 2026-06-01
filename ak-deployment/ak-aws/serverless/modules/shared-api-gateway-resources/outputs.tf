output "cloudwatch_role_arn" {
  description = "ARN of the shared CloudWatch IAM role for API Gateway"
  value       = aws_iam_role.cloudwatch.arn
}

output "cloudwatch_role_id" {
  description = "ID of the shared CloudWatch IAM role for API Gateway"
  value       = aws_iam_role.cloudwatch.id
}

output "cloudwatch_role_name" {
  description = "Name of the shared CloudWatch IAM role for API Gateway"
  value       = aws_iam_role.cloudwatch.name
}
