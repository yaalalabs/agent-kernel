# Lambda module configuration for deploying OpenAI Agent Lambda function
module "serverless_agents" {
  source = "../../../ak-deployment/ak-aws/serverless"

  # Basic lambda configuration
  product_alias        = var.product_alias
  env_alias            = var.env_alias
  function_description = "Agent Kernel LangGraph Sample Lambda"
  function_name        = "langgraph-agents"
  handler_path         = "lambda.handler"
  module_name          = var.module_name
  package_path         = "../dist"
  package_type         = "Image"
  region               = var.region
  memory_size          = 512
  timeout              = 60

  # Environment variables passed to lambda
  environment_variables = {
    "OPENAI_API_KEY" = var.openai_api_key
  }
}
