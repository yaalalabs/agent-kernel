locals {
  subnet_ids                   = var.subnet_ids
  lambda_kms_key_arn          = var.lambda_kms_key_arn
  cloudwatch_kms_key_arn      = var.cloudwatch_kms_key_arn
  
  # Response handler configuration
  response_handler_function_name = var.response_handler.function_name
  response_handler_function_description = var.response_handler.function_description
  response_handler_timeout       = var.response_handler.timeout
  response_handler_memory_size   = var.response_handler.memory_size
  response_handler_handler_path  = var.response_handler.handler_path
  response_handler_layers        = var.response_handler.layers
  response_handler_env_vars      = var.response_handler.environment_variables
  
  # Queue configuration
  output_queue_arn                       = var.queue_config.output_queue_arn
  batch_size                             = var.queue_config.batch_size
  maximum_batching_window_in_seconds     = var.queue_config.maximum_batching_window_in_seconds
  
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

# VPC execution policy
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
        Resource = local.output_queue_arn
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

# WebSocket connections table permissions (conditional on websocket_connections_table_arn)
resource "aws_iam_policy" "response_handler_websocket_connections_policy" {
  count = var.websocket_connections_table_arn != null ? 1 : 0
  name  = "${var.product_alias}-${var.env_alias}-${var.module_name}-${local.response_handler_function_name}-websocket-connections"
  
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
          var.websocket_connections_table_arn,
          "${var.websocket_connections_table_arn}/index/*"
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "response_handler_websocket_connections_attachment" {
  count      = var.websocket_connections_table_arn != null ? 1 : 0
  role       = aws_iam_role.response_handler_lambda_role.name
  policy_arn = aws_iam_policy.response_handler_websocket_connections_policy[0].arn
}

# API Gateway Management API permissions for WebSocket (conditional on websocket_connections_table_arn)
resource "aws_iam_policy" "response_handler_apigateway_management_policy" {
  count = var.websocket_connections_table_arn != null ? 1 : 0
  name  = "${var.product_alias}-${var.env_alias}-${var.module_name}-${local.response_handler_function_name}-apigateway-management"
  
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "execute-api:ManageConnections"
        ]
        Resource = "arn:aws:execute-api:*:*:*"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "response_handler_apigateway_management_attachment" {
  count      = var.websocket_connections_table_arn != null ? 1 : 0
  role       = aws_iam_role.response_handler_lambda_role.name
  policy_arn = aws_iam_policy.response_handler_apigateway_management_policy[0].arn
}

# Response Handler Lambda Function
module "response_handler_lambda" {
  source  = "terraform-aws-modules/lambda/aws"
  version = "8.0.1"

  function_name          = "${var.product_alias}-${var.env_alias}-${var.module_name}-${local.response_handler_function_name}"
  description            = local.response_handler_function_description
  handler                = local.response_handler_handler_path
  runtime                = var.module_type == "nodejs" ? "nodejs22.x" : "python3.12"
  create_role            = false
  lambda_role            = aws_iam_role.response_handler_lambda_role.arn
  local_existing_package = "${path.module}/response_handler_dist.zip"
  create_package         = false
  package_type           = "Zip"
  create_layer           = false
  layers                 = local.response_handler_layers

  use_existing_cloudwatch_log_group = false
  cloudwatch_logs_retention_in_days = 90
  attach_cloudwatch_logs_policy     = true

  vpc_subnet_ids         = local.subnet_ids
  vpc_security_group_ids = var.security_group_id != "" ? [var.security_group_id] : []

  environment_variables = merge(
    local.response_handler_env_vars,
    local.redis_response_store != null ? {
      AK_EXECUTION__RESPONSE_STORE__REDIS__URL = local.redis_response_store.url
      AK_EXECUTION__RESPONSE_STORE__REDIS__PREFIX = local.redis_response_store.prefix
      AK_EXECUTION__RESPONSE_STORE__REDIS__TTL = tostring(local.redis_response_store.ttl)
    } : {},
    local.dynamodb_response_store != null ? {
      AK_EXECUTION__RESPONSE_STORE__DYNAMODB__TABLE_NAME = local.dynamodb_response_store.table_name
      AK_EXECUTION__RESPONSE_STORE__DYNAMODB__TTL = tostring(local.dynamodb_response_store.ttl)
    } : {},
    var.websocket_connections_table_name != null ? {
      AK_EXECUTION__WEBSOCKET_CONNECTION_TABLE = var.websocket_connections_table_name
    } : {}
  )

  timeout     = local.response_handler_timeout
  memory_size = local.response_handler_memory_size

  kms_key_arn                = local.lambda_kms_key_arn
  cloudwatch_logs_kms_key_id = local.cloudwatch_kms_key_arn
}

# SQS Event Source Mapping for Output Queue
resource "aws_lambda_event_source_mapping" "response_handler_output_queue" {
  event_source_arn = local.output_queue_arn
  function_name    = module.response_handler_lambda.lambda_function_name
  batch_size       = local.batch_size
  
  # Configuring maximum batching window
  maximum_batching_window_in_seconds = local.maximum_batching_window_in_seconds
  
  # Configuring partial batch failure handling
  function_response_types = ["ReportBatchItemFailures"]
}

