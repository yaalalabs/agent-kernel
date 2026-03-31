locals {
  package_file_name = "source_code.zip"
}

resource "aws_iam_role" "lambda_role" {
  name = "${var.product_alias}-${var.env_alias}-${var.module_name}-${var.function_name}-lambda-role"
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

resource "aws_iam_role_policy_attachment" "lambda_role_attachment" {
  role       = aws_iam_role.lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaRole"
}

resource "aws_iam_role_policy_attachment" "lambda_basic_execution_role_attachment" {
  role       = aws_iam_role.lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy_attachment" "lambda_vpc_execution_role_attachment" {
  role       = aws_iam_role.lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

resource "aws_iam_policy" "lambda_dynamodb_describe_policy" {
  count = var.create_dynamodb_memory_table == true ? 1 : 0
  name  = "${var.product_alias}-${var.env_alias}-${var.module_name}-${var.function_name}-dynamodb"
  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Effect = "Allow",
        Action = [
          "dynamodb:DescribeTable",
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:UpdateItem",
          "dynamodb:DeleteItem",
          "dynamodb:Query",
          "dynamodb:Scan"
        ],
        Resource = var.dynamodb_memory_table_arn
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_dynamodb_describe_attachment" {
  count      = var.create_dynamodb_memory_table == true ? 1 : 0
  role       = aws_iam_role.lambda_role.name
  policy_arn = aws_iam_policy.lambda_dynamodb_describe_policy[0].arn
}

resource "aws_iam_policy" "lambda_dynamodb_multimodal_describe_policy" {
  count = var.create_dynamodb_multimodal_memory_table == true ? 1 : 0
  name  = "${var.product_alias}-${var.env_alias}-${var.module_name}-${var.function_name}-ddb-mm"
  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Effect = "Allow",
        Action = [
          "dynamodb:DescribeTable",
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:UpdateItem",
          "dynamodb:DeleteItem",
          "dynamodb:Query",
          "dynamodb:Scan"
        ],
        Resource = [
          var.dynamodb_multimodal_memory_table_arn,
          "${var.dynamodb_multimodal_memory_table_arn}/index/*"
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_dynamodb_multimodal_describe_attachment" {
  count      = var.create_dynamodb_multimodal_memory_table == true ? 1 : 0
  role       = aws_iam_role.lambda_role.name
  policy_arn = aws_iam_policy.lambda_dynamodb_multimodal_describe_policy[0].arn
}

# Response store DynamoDB permissions
resource "aws_iam_policy" "lambda_response_store_dynamodb_policy" {
  count = var.response_store_dynamodb != null ? 1 : 0
  name  = "${var.product_alias}-${var.env_alias}-${var.module_name}-${var.function_name}-response-store-ddb"

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
          var.response_store_dynamodb.table_arn,
          "${var.response_store_dynamodb.table_arn}/index/*"
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_response_store_dynamodb_attachment" {
  count      = var.response_store_dynamodb != null ? 1 : 0
  role       = aws_iam_role.lambda_role.name
  policy_arn = aws_iam_policy.lambda_response_store_dynamodb_policy[0].arn
}

# SQS permissions for RequestHandler Lambda (conditional on scalable_mode)
resource "aws_iam_policy" "lambda_sqs_policy" {
  count = var.scalable_mode ? 1 : 0
  name  = "${var.product_alias}-${var.env_alias}-${var.module_name}-${var.function_name}-sqs"
  
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "sqs:SendMessage",
          "sqs:GetQueueAttributes"
        ]
        Resource = var.input_queue_arn
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_sqs_attachment" {
  count      = var.scalable_mode ? 1 : 0
  role       = aws_iam_role.lambda_role.name
  policy_arn = aws_iam_policy.lambda_sqs_policy[0].arn
}

# WebSocket connections table permissions (conditional on websocket_connections_table_arn)
resource "aws_iam_policy" "lambda_websocket_connections_policy" {
  count = var.enable_websocket_permissions ? 1 : 0
  name  = "${var.product_alias}-${var.env_alias}-${var.module_name}-${var.function_name}-websocket-connections"
  
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

resource "aws_iam_role_policy_attachment" "lambda_websocket_connections_attachment" {
  count      = var.enable_websocket_permissions ? 1 : 0
  role       = aws_iam_role.lambda_role.name
  policy_arn = aws_iam_policy.lambda_websocket_connections_policy[0].arn
}

# API Gateway Management API permissions for WebSocket (conditional on websocket_connections_table_arn)
resource "aws_iam_policy" "lambda_apigateway_management_policy" {
  count = var.enable_websocket_permissions ? 1 : 0
  name  = "${var.product_alias}-${var.env_alias}-${var.module_name}-${var.function_name}-apigateway-management"
  
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

resource "aws_iam_role_policy_attachment" "lambda_apigateway_management_attachment" {
  count      = var.enable_websocket_permissions ? 1 : 0
  role       = aws_iam_role.lambda_role.name
  policy_arn = aws_iam_policy.lambda_apigateway_management_policy[0].arn
}

data "aws_s3_object" "source_code" {
  count  = (var.package_type == "S3Zip") ? 1 : 0
  bucket = var.source_bucket
  key    = "${var.product_alias}/${var.region}/${var.env_alias}/${var.module_name}/lambda/${local.package_file_name}"
}

resource "aws_signer_signing_job" "handler_lambda_signing_job" {
  count = (var.is_production) && (var.package_type != "S3Zip") ? 1 : 0

  profile_name = var.lambda_signer_profile_name
  source {
    s3 {
      bucket  = var.source_bucket
      key     = data.aws_s3_object.source_code[0].key
      version = data.aws_s3_object.source_code[0].version_id
    }
  }
  destination {
    s3 {
      bucket = var.source_bucket
      prefix = "${data.aws_s3_object.source_code[0].key}/signed/${data.aws_s3_object.source_code[0].version_id}"
    }
  }
  ignore_signing_job_failure = false
}

data "aws_s3_object" "signed_component_code" {
  count = (var.is_production) && (var.package_type != "S3Zip") ? 1 : 0

  bucket = aws_signer_signing_job.handler_lambda_signing_job[0].signed_object[0].s3[0].bucket
  key    = aws_signer_signing_job.handler_lambda_signing_job[0].signed_object[0].s3[0].key

  depends_on = [
    aws_signer_signing_job.handler_lambda_signing_job[0]
  ]
}

resource "aws_security_group" "lambda" {
  name        = "${var.product_alias}-${var.env_alias}-lambda-sg"
  description = "Security group for Lambda functions"
  vpc_id      = var.vpc_id

  egress {
    from_port = 0
    to_port   = 0
    protocol  = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.product_alias}-${var.env_alias}-lambda-sg"
  }
}

module "lambda_deployment" {
  source  = "terraform-aws-modules/lambda/aws"
  version = "8.0.1"

  function_name          = "${var.product_alias}-${var.env_alias}-${var.module_name}-${var.function_name}"
  description            = var.function_description
  handler                = var.handler_path
  runtime                = var.module_type == "nodejs" ? "nodejs22.x" : "python3.12"
  create_role            = false
  lambda_role            = aws_iam_role.lambda_role.arn
  image_uri              = var.package_type == "Image" ? var.docker_image_uri : null
  local_existing_package = var.package_type == "LocalZip" ? var.package_path : null
  create_package         = false
  package_type           = var.package_type == "Image" ? "Image" : "Zip"
  create_layer = false # to control creation of the Lambda Layer and related resources
  layers                 = var.layers

  use_existing_cloudwatch_log_group = false
  cloudwatch_logs_retention_in_days = var.cloudwatch_logs_retention_in_days
  attach_cloudwatch_logs_policy     = true
  attach_dead_letter_policy         = false
  attach_network_policy             = false
  attach_tracing_policy             = false
  attach_async_event_policy         = false

  vpc_subnet_ids          = var.subnet_ids
  vpc_security_group_ids = [aws_security_group.lambda.id]
  code_signing_config_arn = (var.package_type == "S3Zip" && var.is_production == true) ? var.lambda_signing_config_arn : null

  s3_existing_package = (var.package_type == "S3Zip") ? {
    bucket     = var.is_production ? data.aws_s3_object.signed_component_code[0].bucket : data.aws_s3_object.source_code[0].bucket
    key        = var.is_production ? data.aws_s3_object.signed_component_code[0].key : data.aws_s3_object.source_code[0].key
    version_id = var.is_production ? null : data.aws_s3_object.source_code[0].version_id
  } : {}

  environment_variables = merge(var.environment_variables, {
      API_BASE_PATH = var.api_base_path
      API_VERSION = var.api_version
      AGENT_ENDPOINT = var.agent_endpoint
    },
      var.redis_url != null ? {
      AK_SESSION__REDIS__URL = var.redis_url
    } : {},
      var.dynamodb_memory_table_arn != null ? {
      AK_SESSION__DYNAMODB__TABLE_NAME = var.dynamodb_memory_table_name
    } : {},
      var.dynamodb_multimodal_memory_table_arn != null ? {
      AK_MULTIMODAL__DYNAMODB__TABLE_NAME = var.dynamodb_multimodal_memory_table_name
    } : {},
      var.response_store_redis != null ? {
      AK_EXECUTION__RESPONSE_STORE__REDIS__URL = var.response_store_redis.url
    } : {},
      var.response_store_dynamodb != null ? {
      AK_EXECUTION__RESPONSE_STORE__DYNAMODB__TABLE_NAME = var.response_store_dynamodb.table_name
    } : {},
      var.input_queue_url != null ? {
      AK_EXECUTION__QUEUES__INPUT_QUEUE_URL = var.input_queue_url
    } : {},
      var.websocket_connections_table_name != null ? {
      AK_EXECUTION__WEBSOCKET_CONNECTION_TABLE = var.websocket_connections_table_name
    } : {}
  )
  event_source_mapping = var.event_source_mapping

  timeout     = var.timeout
  memory_size = var.memory_size

  kms_key_arn                = var.lambda_kms_key_arn != null ? var.lambda_kms_key_arn : null
  cloudwatch_logs_kms_key_id = var.cloudwatch_kms_key_arn != null ? var.cloudwatch_kms_key_arn : null
}
