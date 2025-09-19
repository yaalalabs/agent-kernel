# Lambda module configuration for deploying GOogle Agent Lambda function
module "serverless_agents" {
  source = "../../../../ak-deployment/ak-aws/serverless"
  # version = "0.1.0-a2"

  # Basic lambda configuration
  product_alias        = var.product_alias
  env_alias            = var.env_alias
  function_description = "Agent Kernel Google Sample Lambda"
  function_name        = "google-agents"
  handler_path         = "lambda.handler"
  module_name          = var.module_name
  package_path         = "../dist.zip"
  memory_size          = 256
  create_redis_cluster = true
  product_display_name = "AK Google Serverless Example"
  region               = var.region

  # Environment variables passed to lambda
  environment_variables = {
    "GEMINI_API_KEY" = var.gemini_api_key
  }
}
