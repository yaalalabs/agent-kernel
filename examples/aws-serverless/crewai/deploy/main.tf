# Lambda module configuration for deploying OpenAI Agent Lambda function
module "serverless_agents" {
  source = "yaalalabs/ak-serverless/aws"
  version = "0.2.13"

  # Basic lambda configuration
  product_alias        = var.product_alias
  env_alias            = var.env_alias
  function_description = "Agent Kernel CrewAI Sample Lambda"
  function_name        = "crewai-agents"
  handler_path         = "lambda.handler"
  module_name          = var.module_name
  package_path         = "../dist"
  package_type         = "Image"
  region               = var.region
  vpc_id               = var.vpc_id
  private_subnet_ids   = var.private_subnet_ids
  memory_size          = 512
  timeout              = 60
  product_display_name = "AK CrewAI Serverless Example"

  # Environment variables passed to lambda
  environment_variables = {
    OPENAI_API_KEY     = var.openai_api_key,
    CREWAI_STORAGE_DIR = "/tmp/crewai",
    EMBEDCHAIN_DB_PATH = "/tmp/crewai/embedchain.db",
    HOME               = "/tmp"
  }
}
