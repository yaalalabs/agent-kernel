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


module source_storage {
  count                = (var.package_type == "S3Zip") ? 1 : 0
  source               = "app.terraform.io/yaalalabs/ak-s3/aws"
  version              = "0.0.1-rc2"
  region               = var.region
  env_alias            = var.env_alias
  is_production        = var.is_production
  product_alias        = var.product_alias
  product_display_name = var.product_display_name
  s3_kms_key_id        = ""
}

module source_package {
  count            = (var.package_type == "S3Zip") ? 1 : 0
  source           = "app.terraform.io/yaalalabs/ak-lambda-package/aws"
  version          = "0.0.1-rc2"
  env_alias        = var.env_alias
  module_name      = var.module_name
  package_dir_path = var.package_path
  product_alias    = var.product_alias
  s3_bucket        = module.source_storage[0].source_storage_s3_bucket
  depends_on = [module.source_storage]
}

module docker_image {
  count         = (var.package_type == "Image") ? 1 : 0
  source        = "app.terraform.io/yaalalabs/ak-lambda-docker/aws"
  version       = "0.0.1-rc2"
  env_alias     = var.env_alias
  module_name   = var.module_name
  product_alias = var.product_alias
  source_path   = var.package_path
}

data "aws_s3_object" "source_code" {
  count  = (var.package_type == "S3Zip") ? 1 : 0
  bucket = module.source_storage[0].source_storage_s3_bucket
  key    = "${var.product_alias}/${var.region}/${var.env_alias}/${var.module_name}/lambda/${local.package_file_name}"
  depends_on = [module.source_package]
}

resource "aws_signer_signing_job" "handler_lambda_signing_job" {
  count = (var.is_production) && (var.package_type != "S3Zip") ? 1 : 0

  profile_name = local.lambda_signer_profile_name
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

module "lambda_deployment" {
  source  = "terraform-aws-modules/lambda/aws"
  version = "8.0.1"

  function_name          = "${var.product_alias}-${var.env_alias}-${var.module_name}-${var.function_name}"
  description            = var.function_description
  handler                = var.handler_path
  runtime                = var.module_type == "nodejs" ? "nodejs22.x" : "python3.12"
  create_role            = false
  lambda_role            = aws_iam_role.lambda_role.arn
  image_uri              = var.package_type == "Image" ? module.docker_image[0].docker_image_uri : null
  local_existing_package = var.package_type == "LocalZip" ? var.package_path : null
  create_package         = false
  package_type           = var.package_type == "Image" ? "Image" : "Zip"
  create_layer = false # to control creation of the Lambda Layer and related resources
  layers = var.layers

  #create cloudwatch alarm for the lambda
  use_existing_cloudwatch_log_group = false
  cloudwatch_logs_retention_in_days = 90

  #cloudwatch log permissions
  attach_cloudwatch_logs_policy = true
  #SNS/SQS dead letter notification policy
  attach_dead_letter_policy = false
  #elastic network interface permissions - already set in global/permissions
  attach_network_policy = false
  #aws x-ray permissions
  attach_tracing_policy = false

  attach_async_event_policy = false

  # vpc_subnet_ids          = local.lambda_subnet_ids
  # vpc_security_group_ids  = [local.lambda_sg_id]
  code_signing_config_arn = (var.package_type == "S3Zip" && var.is_production == true) ? local.lambda_signing_config_arn : null

  s3_existing_package = (var.package_type == "S3Zip") ? {
    bucket     = var.is_production ? data.aws_s3_object.signed_component_code[0].bucket : data.aws_s3_object.source_code[0].bucket
    key        = var.is_production ? data.aws_s3_object.signed_component_code[0].key : data.aws_s3_object.source_code[0].key
    version_id = var.is_production ? null : data.aws_s3_object.source_code[0].version_id
  } : {}

  environment_variables = var.environment_variables
  event_source_mapping  = var.event_source_mapping

  timeout     = var.timeout
  memory_size = var.memory_size

  kms_key_arn                = local.lambda_kms_key_arn != null ? local.lambda_kms_key_arn : null
  cloudwatch_logs_kms_key_id = local.cloudwatch_kms_key_arn != null ? local.cloudwatch_kms_key_arn : null
}