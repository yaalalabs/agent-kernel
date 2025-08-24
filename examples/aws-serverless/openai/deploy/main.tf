# Lambda module configuration for deploying OpenAI Agent Lambda function
module "serverless_agents" {
  source = "../../../../ak-deployment/ak-aws/serverless"
  # version = "0.0.1-rc3"

  # Basic lambda configuration
  product_alias        = var.product_alias
  env_alias            = var.env_alias
  function_description = "Agent Kernel OpenAI Sample Lambda"
  function_name        = "openai-agents"
  handler_path         = "lambda.handler"
  module_name          = var.module_name
  package_path         = "../dist.zip"
  memory_size          = 256
  product_display_name = "AK OpenAI Serverless Example"
  region               = var.region
  enable_redis_memory  = true

  # Environment variables passed to lambda
  environment_variables = {
    "OPENAI_API_KEY" = var.openai_api_key
  }
}
