locals {
  package_file_name = "source_code.zip"
}

resource "aws_iam_role" "authorizer_lambda_role" {
  name = "${var.product_alias}-${var.env_alias}-${var.authorizer_module_name}-${var.authorizer_function_name}-lambda-role"
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

  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "authorizer_lambda_role_attachment" {
  role       = aws_iam_role.authorizer_lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaRole"
}

resource "aws_iam_role_policy_attachment" "authorizer_lambda_basic_execution_role_attachment" {
  role       = aws_iam_role.authorizer_lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy_attachment" "authorizer_lambda_vpc_execution_role_attachment" {
  count      = length(var.subnet_ids) > 0 ? 1 : 0
  role       = aws_iam_role.authorizer_lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

resource "aws_security_group" "authorizer_lambda" {
  count = length(var.security_group_ids) == 0 && length(var.subnet_ids) > 0 ? 1 : 0
  name        = "${var.product_alias}-${var.env_alias}-authorizer-lambda-sg"
  description = "Security group for authorizer Lambda functions"
  vpc_id      = var.vpc_id

  egress {
    from_port = 0
    to_port   = 0
    protocol  = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(var.tags, {
    Name = "${var.product_alias}-${var.env_alias}-authorizer-lambda-sg"
  })
}

data "aws_s3_object" "authorizer_source_code" {
  count  = (var.authorizer_package_type == "S3Zip") ? 1 : 0
  bucket = module.authorizer_source_storage[0].source_storage_s3_bucket
  key    = "${var.product_alias}/${var.region}/${var.env_alias}/${var.authorizer_module_name}/lambda/${local.package_file_name}"
  depends_on = [module.authorizer_source_package]
}

resource "aws_signer_signing_job" "authorizer_lambda_signing_job" {
  count = (var.is_production) && (var.authorizer_package_type != "S3Zip") ? 1 : 0

  profile_name = var.lambda_signer_profile_name
  source {
    s3 {
      bucket  = module.authorizer_source_storage[0].source_storage_s3_bucket
      key     = data.aws_s3_object.authorizer_source_code[0].key
      version = data.aws_s3_object.authorizer_source_code[0].version_id
    }
  }
  destination {
    s3 {
      bucket = module.authorizer_source_storage[0].source_storage_s3_bucket
      prefix = "${data.aws_s3_object.authorizer_source_code[0].key}/signed/${data.aws_s3_object.authorizer_source_code[0].version_id}"
    }
  }
  ignore_signing_job_failure = false
}

data "aws_s3_object" "signed_authorizer_code" {
  count = (var.is_production) && (var.authorizer_package_type != "S3Zip") ? 1 : 0

  bucket = aws_signer_signing_job.authorizer_lambda_signing_job[0].signed_object[0].s3[0].bucket
  key    = aws_signer_signing_job.authorizer_lambda_signing_job[0].signed_object[0].s3[0].key

  depends_on = [
    aws_signer_signing_job.authorizer_lambda_signing_job[0]
  ]
}

module "authorizer_lambda_deployment" {
  source  = "terraform-aws-modules/lambda/aws"
  version = "8.0.1"

  function_name          = "${var.product_alias}-${var.env_alias}-${var.authorizer_module_name}-${var.authorizer_function_name}"
  description            = var.authorizer_function_description
  handler                = var.authorizer_handler_path
  runtime                = var.module_type == "nodejs" ? "nodejs22.x" : "python3.12"
  create_role            = false
  lambda_role            = aws_iam_role.authorizer_lambda_role.arn
  image_uri              = var.authorizer_package_type == "Image" ? module.authorizer_docker_image[0].docker_image_uri : null
  local_existing_package = var.authorizer_package_type == "LocalZip" ? var.authorizer_package_path : null
  create_package         = false
  package_type           = var.authorizer_package_type == "Image" ? "Image" : "Zip"
  create_layer = false
  layers                 = var.layers

  use_existing_cloudwatch_log_group = false
  cloudwatch_logs_retention_in_days = 90
  attach_cloudwatch_logs_policy     = true
  attach_dead_letter_policy         = false
  attach_network_policy             = false
  attach_tracing_policy             = false
  attach_async_event_policy         = false

  vpc_subnet_ids = length(var.subnet_ids) > 0 ? var.subnet_ids : null
  vpc_security_group_ids = length(var.security_group_ids) > 0 ? var.security_group_ids : (length(var.subnet_ids) > 0 ? [aws_security_group.authorizer_lambda[0].id] : null)
  code_signing_config_arn = (var.authorizer_package_type == "S3Zip" && var.is_production == true) ? var.lambda_signing_config_arn : null

  s3_existing_package = (var.authorizer_package_type == "S3Zip") ? {
    bucket     = var.is_production ? data.aws_s3_object.signed_authorizer_code[0].bucket : data.aws_s3_object.authorizer_source_code[0].bucket
    key        = var.is_production ? data.aws_s3_object.signed_authorizer_code[0].key : data.aws_s3_object.authorizer_source_code[0].key
    version_id = var.is_production ? null : data.aws_s3_object.authorizer_source_code[0].version_id
  } : {}

  environment_variables = var.authorizer_environment_variables

  timeout     = var.timeout
  memory_size = var.memory_size

  kms_key_arn                = var.lambda_kms_key_arn
  cloudwatch_logs_kms_key_id = var.cloudwatch_kms_key_arn

  tags = var.tags
}