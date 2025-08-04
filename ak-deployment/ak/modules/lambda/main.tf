locals {
  source_code_s3 = "${var.product_alias}-${var.env_alias}-source-storage-${data.aws_caller_identity.current.account_id}-${data.aws_region}"
  package_file_name  = "source_code.zip"
}

data "aws_s3_object" "source_code" {
  count  = (var.package_type == "Image") ? 0 : 1
  bucket = local.source_code_s3
  key    = "${var.product_alias}/${var.region}/${var.env_alias}/${var.module_name}/lambda/${local.package_file_name}"
}

resource "aws_signer_signing_job" "handler_lambda_signing_job" {
  count = (var.is_production) && (var.package_type != "Image") ? 1 : 0

  profile_name = local.lambda_signer_profile_name
  source {
    s3 {
      bucket  = local.source_code_s3
      key     = data.aws_s3_object.source_code[0].key
      version = data.aws_s3_object.source_code[0].version_id
    }
  }
  destination {
    s3 {
      bucket = local.source_code_s3
      prefix = "${data.aws_s3_object.source_code[0].key}/signed/${data.aws_s3_object.source_code[0].version_id}"
    }
  }
  ignore_signing_job_failure = false
}

data "aws_s3_object" "signed_component_code" {
  count = (var.is_production) && (var.package_type != "Image") ? 1 : 0

  bucket = aws_signer_signing_job.handler_lambda_signing_job[0].signed_object[0].s3[0].bucket
  key    = aws_signer_signing_job.handler_lambda_signing_job[0].signed_object[0].s3[0].key

  depends_on = [
    aws_signer_signing_job.handler_lambda_signing_job[0]
  ]
}

module "lambda_deployment" {
  source  = "terraform-aws-modules/lambda/aws"
  version = "7.20.0"

  function_name = "${var.product_alias}-${var.env_alias}${var.module_name}-${var.function_name}"
  description   = var.function_description
  handler       = var.handler_path
  runtime       = var.module_type == "nodejs" ? "nodejs22.x" : "python3.12"
  lambda_role   = var.role_arn
  image_uri     = var.image_uri
  package_type  = var.package_type

  layers = var.layers

  create_package = false
  create_layer   = false # to control creation of the Lambda Layer and related resources
  create_role    = false # to control creation of the IAM role and policies required for Lambda Function

  #create cloudwatch alarm for the lambda
  use_existing_cloudwatch_log_group = false
  cloudwatch_logs_retention_in_days = 90

  #cloudwatch log permissions - already set in global/permissions
  attach_cloudwatch_logs_policy = false
  #SNS/SQS dead letter notification policy
  attach_dead_letter_policy = false
  #elastic network interface permissions - already set in global/permissions
  attach_network_policy = false
  #aws x-ray permissions
  attach_tracing_policy = false

  attach_async_event_policy = false

  # vpc_subnet_ids          = local.lambda_subnet_ids
  # vpc_security_group_ids  = [local.lambda_sg_id]
  code_signing_config_arn = (var.package_type == "Image") ? null : local.lambda_signing_config_arn

  s3_existing_package = (var.package_type == "Image") ? {} : {
    bucket     = local.lambda_signer_profile_name != null ? data.aws_s3_object.signed_component_code[0].bucket : data.aws_s3_object.source_code[0].bucket
    key        = local.lambda_signer_profile_name != null ? data.aws_s3_object.signed_component_code[0].key : data.aws_s3_object.source_code[0].key
    version_id = local.lambda_signer_profile_name != null ? null : data.aws_s3_object.source_code[0].version_id
  }

  environment_variables = var.environment_variables
  event_source_mapping  = var.event_source_mapping

  timeout     = var.timeout
  memory_size = var.memory_size

  kms_key_arn                = local.lambda_kms_key_arn != null ? local.lambda_kms_key_arn : null
  cloudwatch_logs_kms_key_id = local.cloudwatch_kms_key_arn != null ? local.cloudwatch_kms_key_arn : null
}
