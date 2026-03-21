# Response Handler Lambda Configuration
locals {
  subnet_ids                   = var.subnet_ids
  lambda_kms_key_arn          = var.lambda_kms_key_arn
  cloudwatch_kms_key_arn      = var.cloudwatch_kms_key_arn
  
  # Response handler configuration
  response_handler_function_name = var.response_handler.function_name
  response_handler_timeout       = var.response_handler.timeout
  response_handler_memory_size   = var.response_handler.memory_size
  
  # Response store configuration (null in async mode)
  redis_response_store = var.response_store != null ? var.response_store.redis : null
  dynamodb_response_store = var.response_store != null ? var.response_store.dynamodb : null
}

# IAM Role for Response Handler Lambda
resource "aws_iam_role" "response_handler_lambda_role" {
  name = "${var.product_alias}-${var.env_alias}-${var.module_name}-${local.response_handler_function_name}-lambda-role"
  
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
resource "aws_iam_role_policy_attachment" "response_handler_basic_execution" {
  role       = aws_iam_role.response_handler_lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# VPC execution policy (if using VPC)
resource "aws_iam_role_policy_attachment" "response_handler_vpc_execution" {
  role       = aws_iam_role.response_handler_lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

# SQS permissions for response handler
resource "aws_iam_policy" "response_handler_sqs_policy" {
  name = "${var.product_alias}-${var.env_alias}-${var.module_name}-${local.response_handler_function_name}-sqs"
  
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:GetQueueAttributes",
          "sqs:ChangeMessageVisibility"
        ]
        Resource = "*"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "response_handler_sqs_attachment" {
  role       = aws_iam_role.response_handler_lambda_role.name
  policy_arn = aws_iam_policy.response_handler_sqs_policy.arn
}

# DynamoDB permissions (if DynamoDB is used)
resource "aws_iam_policy" "response_handler_dynamodb_policy" {
  count = local.dynamodb_response_store != null ? 1 : 0
  name  = "${var.product_alias}-${var.env_alias}-${var.module_name}-${local.response_handler_function_name}-dynamodb"
  
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
        Resource = local.dynamodb_response_store.table_arn
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "response_handler_dynamodb_attachment" {
  count      = local.dynamodb_response_store != null ? 1 : 0
  role       = aws_iam_role.response_handler_lambda_role.name
  policy_arn = aws_iam_policy.response_handler_dynamodb_policy[0].arn
}

# Response Handler Lambda Function
module "response_handler_lambda" {
  source  = "terraform-aws-modules/lambda/aws"
  version = "8.0.1"

  function_name          = "${var.product_alias}-${var.env_alias}-${var.module_name}-${local.response_handler_function_name}"
  description            = "Response handler Lambda for processing SQS messages and storing responses"
  handler                = "response_handler.handler"
  runtime                = var.module_type == "nodejs" ? "nodejs22.x" : "python3.12"
  create_role            = false
  lambda_role            = aws_iam_role.response_handler_lambda_role.arn
  local_existing_package = "${path.module}/response_handler_dist.zip" # TODO:: has to change based on the Package_type
  create_package         = false
  package_type           = "Zip" # TODO:: LocalZip and Image mode has to be supported
  create_layer = false # to control creation of the Lambda Layer and related resources

  use_existing_cloudwatch_log_group = false
  cloudwatch_logs_retention_in_days = 90
  attach_cloudwatch_logs_policy     = true

  vpc_subnet_ids         = local.subnet_ids
  vpc_security_group_ids = var.security_group_id != "" ? [var.security_group_id] : []

  environment_variables = merge(
    var.environment_variables,
    local.redis_response_store != null ? {
      AK_RESPONSE_STORE__REDIS__URL = local.redis_response_store.url
      AK_RESPONSE_STORE__REDIS__PREFIX = local.redis_response_store.prefix
      AK_RESPONSE_STORE__REDIS__TTL = tostring(local.redis_response_store.ttl)
    } : {},
    local.dynamodb_response_store != null ? {
      AK_RESPONSE_STORE__DYNAMODB__TABLE_NAME = local.dynamodb_response_store.table_name
      AK_RESPONSE_STORE__DYNAMODB__TTL = tostring(local.dynamodb_response_store.ttl)
    } : {}
  )

  timeout     = local.response_handler_timeout
  memory_size = local.response_handler_memory_size

  kms_key_arn                = local.lambda_kms_key_arn
  cloudwatch_logs_kms_key_id = local.cloudwatch_kms_key_arn
}

