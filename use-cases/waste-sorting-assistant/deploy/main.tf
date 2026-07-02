locals {
  lambda_function_name = "waste-sorting-assistant"
}

module "serverless_agents" {
  source  = "yaalalabs/ak-serverless/aws"
  version = "0.6.0"

  product_alias                = var.product_alias
  env_alias                    = var.env_alias
  module_name                  = var.module_name
  product_display_name         = "Waste Sorting Assistant"
  region                       = var.region
  execution_mode               = "rest_sync"
  create_dynamodb_memory_table = true

  request_handler = {
    module_name          = var.module_name
    function_name        = local.lambda_function_name
    function_description = "Agent Kernel OpenAI waste sorting assistant"
    handler_path         = "lambda.handler"
    package_type         = "Image"
    package_path         = "../dist"
    timeout              = 60
    memory_size          = 512

    environment_variables = {
      OPENAI_API_KEY                   = var.openai_api_key
    }
  }
}
