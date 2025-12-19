# Lambda module configuration for deploying Google Agent Lambda function
module "serverless_agents" {
  source = "yaalalabs/ak-serverless/aws"
  version = "0.2.9"

  # Basic lambda configuration
  product_alias        = var.product_alias
  env_alias            = var.env_alias
  function_description = "Agent Kernel ADK Sample Lambda"
  function_name        = "adk-agents"
  handler_path         = "lambda.handler"
  module_name          = var.module_name
  package_path         = "../dist"
  package_type         = "Image"
  region               = var.region
  vpc_id               = "vpc-09033229d67314c1c"
  private_subnet_ids   = ["subnet-00e888e445f16d1b1", "subnet-0ab5240262cd77119"]
  memory_size          = 512
  timeout              = 60
  product_display_name = "AK Google ADK Serverless Example"

  # Environment variables passed to lambda
  environment_variables = {
    OPENAI_API_KEY     = var.openai_api_key,
  }
}
