locals {
  function_name         = var.ws_connection_handler.function_name
  function_description  = var.ws_connection_handler.function_description
  timeout               = var.ws_connection_handler.timeout
  memory_size           = var.ws_connection_handler.memory_size
  handler_path          = var.ws_connection_handler.handler_path
  module_name           = var.ws_connection_handler.module_name
  package_path          = var.ws_connection_handler.package_path
  layers                = var.ws_connection_handler.layers
  environment_variables = var.ws_connection_handler.environment_variables
  cloudwatch_logs_retention_in_days = var.ws_connection_handler.cloudwatch_logs_retention_in_days
}

# IAM Role for WebSocket Connection Handler Lambda
resource "aws_iam_role" "ws_connection_handler_lambda_role" {
  name = "${var.product_alias}-${var.env_alias}-${local.module_name}-${local.function_name}-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })
}

# Basic Lambda execution policy
resource "aws_iam_role_policy_attachment" "ws_connection_handler_basic_execution" {
  role       = aws_iam_role.ws_connection_handler_lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# VPC execution policy
resource "aws_iam_role_policy_attachment" "ws_connection_handler_vpc_execution" {
  role       = aws_iam_role.ws_connection_handler_lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

# DynamoDB permissions for WebSocket connection table
resource "aws_iam_policy" "ws_connection_handler_dynamodb_policy" {
  name = "${var.product_alias}-${var.env_alias}-${local.module_name}-${local.function_name}-dynamodb"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "dynamodb:DescribeTable",
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:UpdateItem",
          "dynamodb:DeleteItem",
          "dynamodb:Query",
          "dynamodb:Scan"
        ]
        Resource = [
          var.websocket_connection_table_arn,
          "${var.websocket_connection_table_arn}/index/*"
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "ws_connection_handler_dynamodb_attachment" {
  role       = aws_iam_role.ws_connection_handler_lambda_role.name
  policy_arn = aws_iam_policy.ws_connection_handler_dynamodb_policy.arn
}

# WebSocket Connection Handler Lambda Function
module "ws_connection_handler_lambda" {
  source  = "terraform-aws-modules/lambda/aws"
  version = "8.0.1"

  function_name          = "${var.product_alias}-${var.env_alias}-${local.module_name}-${local.function_name}"
  description            = local.function_description
  handler                = local.handler_path
  runtime                = var.module_type == "nodejs" ? "nodejs22.x" : "python3.12"
  create_role            = false
  lambda_role            = aws_iam_role.ws_connection_handler_lambda_role.arn
  local_existing_package = local.package_path
  create_package         = false
  package_type           = "Zip"
  create_layer           = false
  layers                 = local.layers

  use_existing_cloudwatch_log_group = false
  cloudwatch_logs_retention_in_days = local.cloudwatch_logs_retention_in_days
  attach_cloudwatch_logs_policy     = true

  vpc_subnet_ids         = var.subnet_ids
  vpc_security_group_ids = var.security_group_id != "" ? [var.security_group_id] : []

  environment_variables = local.environment_variables

  timeout     = local.timeout
  memory_size = local.memory_size

  kms_key_arn                = var.lambda_kms_key_arn
  cloudwatch_logs_kms_key_id = var.cloudwatch_kms_key_arn

  tags = var.tags
}
