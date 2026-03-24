locals {
  package_file_name = "source_code.zip"
}

module "source_storage" {
  count                = (var.package_type == "S3Zip") ? 1 : 0
  source               = "yaalalabs/ak-common/aws//modules/s3"
  version              = "0.2.14"
  region               = var.region
  env_alias            = var.env_alias
  is_production        = var.is_production
  product_alias        = var.product_alias
  product_display_name = var.product_display_name
  s3_kms_key_id        = ""
}

module "source_package" {
  count            = (var.package_type == "S3Zip") ? 1 : 0
  source           = "yaalalabs/ak-common/aws//modules/lambda-package"
  version          = "0.2.14"
  env_alias        = var.env_alias
  region           = var.region
  module_name      = var.module_name
  package_dir_path = var.package_path
  product_alias    = var.product_alias
  s3_bucket        = module.source_storage[0].source_storage_s3_bucket
  depends_on       = [module.source_storage]
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

data "aws_s3_object" "source_code" {
  count  = (var.package_type == "S3Zip") ? 1 : 0
  bucket = module.source_storage[0].source_storage_s3_bucket
  key    = "${var.product_alias}/${var.region}/${var.env_alias}/${var.module_name}/lambda/${local.package_file_name}"
  depends_on = [module.source_package]
}

resource "aws_signer_signing_job" "handler_lambda_signing_job" {
  count = (var.is_production) && (var.package_type != "S3Zip") ? 1 : 0

  profile_name = var.lambda_signer_profile_name
  source {
    s3 {
      bucket  = module.source_storage[0].source_storage_s3_bucket
      key     = data.aws_s3_object.source_code[0].key
      version = data.aws_s3_object.source_code[0].version_id
    }
  }
  destination {
    s3 {
      bucket = module.source_storage[0].source_storage_s3_bucket
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
  cloudwatch_logs_retention_in_days = 90
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
      var.scalable_mode ? {
      AK_EXECUTION__INPUT_QUEUE_URL = var.input_queue_url
    } : {}
  )
  event_source_mapping = var.event_source_mapping

  timeout     = var.timeout
  memory_size = var.memory_size

  kms_key_arn                = var.lambda_kms_key_arn != null ? var.lambda_kms_key_arn : null
  cloudwatch_logs_kms_key_id = var.cloudwatch_kms_key_arn != null ? var.cloudwatch_kms_key_arn : null
}
