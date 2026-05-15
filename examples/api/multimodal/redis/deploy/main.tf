# Lambda module configuration for deploying Multimodal Agent Lambda function
module "serverless_agents" {
  source  = "yaalalabs/ak-serverless/aws"
  version = "0.4.0"

  # Basic lambda configuration
  product_alias        = var.product_alias
  env_alias            = var.env_alias
  module_name          = var.module_name
  create_redis_cluster = true
  product_display_name = "Agent Kernel Multimodal with Redis"
  region               = var.region

  # Request handler configuration
  request_handler = {
    function_description = "Agent Kernel Multimodal with Redis"
    function_name        = "mm-redis"
    handler_path         = "lambda.handler"
    module_name          = var.module_name
    package_path         = "../dist"
    package_type         = "Image"
    memory_size          = 2048
    timeout              = 60
    environment_variables = {
      "OPENAI_API_KEY" = var.openai_api_key
    }
  }
}


