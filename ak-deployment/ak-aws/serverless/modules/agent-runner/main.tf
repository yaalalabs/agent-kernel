locals {
  package_file_name = "source_code.zip"

  agent_runner_function_name = var.agent_runner.function_name
  agent_runner_function_description = var.agent_runner.function_description
  agent_runner_timeout       = var.agent_runner.timeout
  agent_runner_memory_size   = var.agent_runner.memory_size
  agent_runner_package_path  = var.agent_runner.package_path
  agent_runner_package_type  = var.agent_runner.package_type
  agent_runner_handler_path  = var.agent_runner.handler_path
  agent_runner_module_name   = var.agent_runner.module_name
  agent_runner_layers        = var.agent_runner.layers
  agent_runner_env_vars      = var.agent_runner.environment_variables
  # Removed passthrough locals; use var.* directly in resources and modules
  
  queue_input_arn                       = var.queue_config.input_queue_arn
  queue_output_arn                      = var.queue_config.output_queue_arn
  queue_output_url                      = var.queue_config.output_queue_url
  queue_batch_size                      = var.queue_config.batch_size
  queue_batching_window                 = var.queue_config.maximum_batching_window_in_seconds
  queue_input_consumer_max_receive_count = max(1, var.queue_config.input_queue_max_receive_count - 1)
}

resource "aws_iam_policy" "agent_runner_dynamodb_memory_policy" {
  count = var.create_dynamodb_memory_table == true ? 1 : 0
  name  = "${var.product_alias}-${var.env_alias}-${local.agent_runner_function_name}-dynamodb"

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
          Resource = var.dynamodb_memory_table_arn
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "agent_runner_dynamodb_memory_attachment" {
  count      = var.create_dynamodb_memory_table == true ? 1 : 0
  role       = aws_iam_role.agent_runner_lambda_role.name
  policy_arn = aws_iam_policy.agent_runner_dynamodb_memory_policy[0].arn
}

resource "aws_iam_policy" "agent_runner_dynamodb_multimodal_policy" {
  count = var.create_dynamodb_multimodal_memory_table == true ? 1 : 0
  name  = "${var.product_alias}-${var.env_alias}-${local.agent_runner_function_name}-ddb-mm"

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
            var.dynamodb_multimodal_memory_table_arn,
            "${var.dynamodb_multimodal_memory_table_arn}/index/*"
          ]
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "agent_runner_dynamodb_multimodal_attachment" {
  count      = var.create_dynamodb_multimodal_memory_table == true ? 1 : 0
  role       = aws_iam_role.agent_runner_lambda_role.name
  policy_arn = aws_iam_policy.agent_runner_dynamodb_multimodal_policy[0].arn
}

data "aws_s3_object" "source_code" {
  count  = var.agent_runner.package_type == "S3Zip" ? 1 : 0
  bucket = var.source_bucket
  key    = "${var.product_alias}/${var.region}/${var.env_alias}/${local.agent_runner_module_name}/lambda/${local.package_file_name}"
}

resource "aws_signer_signing_job" "agent_runner_lambda_signing_job" {
  count = var.is_production && var.agent_runner.package_type == "S3Zip" ? 1 : 0

  profile_name = var.lambda_signer_profile_name
  source {
    s3 {
      bucket  = data.aws_s3_object.source_code[0].bucket
      key     = data.aws_s3_object.source_code[0].key
      version = data.aws_s3_object.source_code[0].version_id
    }
  }
  destination {
    s3 {
      bucket = data.aws_s3_object.source_code[0].bucket
      prefix = "${data.aws_s3_object.source_code[0].key}/signed/${data.aws_s3_object.source_code[0].version_id}"
    }
  }
  ignore_signing_job_failure = false
}

data "aws_s3_object" "signed_component_code" {
  count = var.is_production && var.agent_runner.package_type == "S3Zip" ? 1 : 0

  bucket = aws_signer_signing_job.agent_runner_lambda_signing_job[0].signed_object[0].s3[0].bucket
  key    = aws_signer_signing_job.agent_runner_lambda_signing_job[0].signed_object[0].s3[0].key

  depends_on = [aws_signer_signing_job.agent_runner_lambda_signing_job[0]]
}

# IAM Role for Agent Runner Lambda
resource "aws_iam_role" "agent_runner_lambda_role" {
  name = "${var.product_alias}-${var.env_alias}-${local.agent_runner_function_name}-lambda-role"
  
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
  name = "${var.product_alias}-${var.env_alias}-${local.agent_runner_function_name}-sqs"
  
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

  function_name          = "${var.product_alias}-${var.env_alias}-${local.agent_runner_function_name}"
  description            = local.agent_runner_function_description
  handler                = local.agent_runner_handler_path
  runtime                = var.module_type == "nodejs" ? "nodejs22.x" : "python3.12"
  create_role            = false
  lambda_role            = aws_iam_role.agent_runner_lambda_role.arn
  image_uri              = var.agent_runner.package_type == "Image" ? var.docker_image_uri : null
  local_existing_package = var.agent_runner.package_type == "LocalZip" ? local.agent_runner_package_path : null
  create_package         = false
  package_type           = local.agent_runner_package_type == "Image" ? "Image" : "Zip"
  create_layer           = false
  layers                 = local.agent_runner_layers

  s3_existing_package = var.agent_runner.package_type == "S3Zip" ? {
    bucket     = var.is_production ? data.aws_s3_object.signed_component_code[0].bucket : data.aws_s3_object.source_code[0].bucket
    key        = var.is_production ? data.aws_s3_object.signed_component_code[0].key : data.aws_s3_object.source_code[0].key
    version_id = var.is_production ? null : data.aws_s3_object.source_code[0].version_id
  } : {}

  code_signing_config_arn = (var.agent_runner.package_type == "S3Zip" && var.is_production) ? var.lambda_signing_config_arn : null

  use_existing_cloudwatch_log_group = false
  cloudwatch_logs_retention_in_days = var.cloudwatch_logs_retention_in_days
  attach_cloudwatch_logs_policy     = true

  vpc_subnet_ids         = var.subnet_ids
  vpc_security_group_ids = var.security_group_id != "" ? [var.security_group_id] : []

  environment_variables = merge(
    local.agent_runner_env_vars,
      var.redis_url != null ? {
        AK_SESSION__REDIS__URL = var.redis_url
      } : {},
      var.dynamodb_memory_table_arn != null ? {
        AK_SESSION__DYNAMODB__TABLE_NAME = var.dynamodb_memory_table_name
      } : {},
      var.dynamodb_multimodal_memory_table_arn != null ? {
        AK_MULTIMODAL__DYNAMODB__TABLE_NAME = var.dynamodb_multimodal_memory_table_name
      } : {},
    {
      AK_EXECUTION__QUEUES__INPUT_QUEUE_MAX_RECEIVE_COUNT  = tostring(local.queue_input_consumer_max_receive_count)
      AK_EXECUTION__QUEUES__OUTPUT_QUEUE_URL = local.queue_output_url
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