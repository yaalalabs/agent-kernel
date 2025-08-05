module "lambda" {
  source = "../../../ak-deployment/ak/modules/lambda"

  product_alias        = var.product_alias
  env_alias            = var.env_alias
  function_description = "Agent Kernel OpenAI Sample Lambda"
  function_name        = "openai-agents"
  handler_path         = "lambda.handler"
  module_name          = var.module_name
  package_path         = "../dist.zip"
  region               = var.region
  environment_variables = {
    "OPENAI_API_KEY" = var.openai_api_key
  }
}