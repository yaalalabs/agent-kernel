locals {
  agent_runner_function_name = var.agent_runner.function_name
  agent_runner_timeout       = var.agent_runner.timeout
  agent_runner_memory_size   = var.agent_runner.memory_size
  agent_runner_package_path  = var.agent_runner.package_path
  agent_runner_package_type  = var.agent_runner.package_type
  agent_runner_handler_path  = var.agent_runner.handler_path
  agent_runner_layers        = var.agent_runner.layers
  agent_runner_env_vars      = var.agent_runner.environment_variables
  
  queue_input_arn            = var.queue_config.input_queue_arn
  queue_output_arn           = var.queue_config.output_queue_arn
  queue_output_url           = var.queue_config.output_queue_url
  queue_batch_size           = var.queue_config.batch_size
  queue_batching_window      = var.queue_config.maximum_batching_window_in_seconds
}

# IAM Role for Agent Runner Lambda
resource "aws_iam_role" "agent_runner_lambda_role" {
  name = "${var.product_alias}-${var.env_alias}-${var.module_name}-${local.agent_runner_function_name}-lambda-role"
  
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
resource "aws_iam_role_policy_attachment" "agent_runner_basic_execution" {
  role       = aws_iam_role.agent_runner_lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# VPC execution policy
resource "aws_iam_role_policy_attachment" "agent_runner_vpc_execution" {
  role       = aws_iam_role.agent_runner_lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

# SQS permissions for agent runner (receive/delete from input queue & send to output queue)
resource "aws_iam_policy" "agent_runner_sqs_policy" {
  name = "${var.product_alias}-${var.env_alias}-${var.module_name}-${local.agent_runner_function_name}-sqs"
  
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
        Resource = local.queue_input_arn
      },
      {
        Effect = "Allow"
        Action = [
          "sqs:SendMessage",
          "sqs:GetQueueAttributes"
        ]
        Resource = local.queue_output_arn
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "agent_runner_sqs_attachment" {
  role       = aws_iam_role.agent_runner_lambda_role.name
  policy_arn = aws_iam_policy.agent_runner_sqs_policy.arn
}

# Agent Runner Lambda Function
module "agent_runner_lambda" {
  source  = "terraform-aws-modules/lambda/aws"
  version = "8.0.1"

  function_name          = "${var.product_alias}-${var.env_alias}-${var.module_name}-${local.agent_runner_function_name}"
  description            = "Agent runner Lambda for processing input queue messages"
  handler                = local.agent_runner_handler_path
  runtime                = var.module_type == "nodejs" ? "nodejs22.x" : "python3.12"
  create_role            = false
  lambda_role            = aws_iam_role.agent_runner_lambda_role.arn
  local_existing_package = local.agent_runner_package_path
  create_package         = false
  package_type           = local.agent_runner_package_type == "Image" ? "Image" : "Zip"
  create_layer           = false
  layers                 = local.agent_runner_layers

  use_existing_cloudwatch_log_group = false
  cloudwatch_logs_retention_in_days = 90
  attach_cloudwatch_logs_policy     = true

  vpc_subnet_ids         = var.subnet_ids
  vpc_security_group_ids = var.security_group_id != "" ? [var.security_group_id] : []

  environment_variables = merge(
    local.agent_runner_env_vars,
    {
      AK_EXECUTION__OUTPUT_QUEUE_URL = local.queue_output_url
    }
  )

  timeout     = local.agent_runner_timeout
  memory_size = local.agent_runner_memory_size

  kms_key_arn                = var.lambda_kms_key_arn
  cloudwatch_logs_kms_key_id = var.cloudwatch_kms_key_arn
}

# SQS Event Source Mapping for Input Queue
resource "aws_lambda_event_source_mapping" "agent_runner_input_queue" {
  event_source_arn = local.queue_input_arn
  function_name    = module.agent_runner_lambda.lambda_function_name
  batch_size       = local.queue_batch_size
  
  # Configure maximum batching window
  maximum_batching_window_in_seconds = local.queue_batching_window
  
  # Configure partial batch failure handling
  function_response_types = ["ReportBatchItemFailures"]
}