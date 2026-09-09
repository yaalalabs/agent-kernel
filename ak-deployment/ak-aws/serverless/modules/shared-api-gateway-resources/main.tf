# Shared API Gateway CloudWatch Logging Module
# This module provides shared CloudWatch resources for both REST and WebSocket API Gateways

# IAM Role for CloudWatch integration (shared between REST and WebSocket APIs)
resource "aws_iam_role" "cloudwatch" {
  name = "${var.product_alias}-${var.env_alias}-api-gateway-cloudwatch-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "apigateway.amazonaws.com"
        }
      }
    ]
  })

  tags = var.tags
}

resource "aws_iam_role_policy" "cloudwatch" {
  name = "${var.product_alias}-${var.env_alias}-api-gateway-cloudwatch-policy"
  role = aws_iam_role.cloudwatch.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:DescribeLogGroups",
          "logs:DescribeLogStreams",
          "logs:PutLogEvents",
          "logs:GetLogEvents",
          "logs:FilterLogEvents"
        ]
        Resource = "*"
      }
    ]
  })
}

# API Gateway Account configuration (singleton per AWS account)
resource "aws_api_gateway_account" "api_gateway" {
  cloudwatch_role_arn = aws_iam_role.cloudwatch.arn
}
