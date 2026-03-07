# DynamoDB table for multimodal attachment storage
resource "aws_dynamodb_table" "multimodal_attachments" {
  name         = "${var.product_alias}-${var.env_alias}-${var.module_name}-attachments"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "session_id"
  range_key    = "attachment_id"

  attribute {
    name = "session_id"
    type = "S"
  }

  attribute {
    name = "attachment_id"
    type = "S"
  }

  ttl {
    attribute_name = "expiry_time"
    enabled        = true
  }
}

# Lambda module configuration for deploying Multimodal Agent Lambda function
module "serverless_agents" {
  source  = "yaalalabs/ak-serverless/aws"
  version = "0.2.13"

  # Basic lambda configuration
  product_alias        = var.product_alias
  env_alias            = var.env_alias
  function_description = "Agent Kernel Multimodal with DynamoDB"
  function_name        = "multimodal-ddb"
  handler_path         = "lambda.handler"
  module_name          = var.module_name
  package_path         = "../dist.zip"
  memory_size          = 256
  product_display_name = "Agent Kernel Multimodal DynamoDB"
  region               = var.region

  # Environment variables passed to lambda
  environment_variables = {
    "OPENAI_API_KEY"                      = var.openai_api_key
    "AK_MULTIMODAL__DYNAMODB__TABLE_NAME" = aws_dynamodb_table.multimodal_attachments.name
  }
}
