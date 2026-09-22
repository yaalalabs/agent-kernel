# Lambda module configuration for deploying OpenAI Agent Lambda function
module "serverless_agents" {
  source  = "yaalalabs/ak-serverless/aws"
  version = "0.9.2"

  providers = { aws = aws, docker = docker }
  # Basic lambda configuration
  prefix               = var.prefix
  region               = var.region
  vpc_id               = var.vpc_id
  private_subnet_ids   = var.private_subnet_ids
  product_display_name = "AK CrewAI Serverless Example"

  # Request handler configuration
  request_handler = {
    function_name        = "crewai-agents"
    function_description = "Agent Kernel CrewAI Sample Lambda"
    handler_path         = "lambda.handler"
    package_path         = "../dist"
    package_type         = "Image"
    memory_size          = 1024
    timeout              = 60
    security_group_id    = var.request_handler_security_group_id
    environment_variables = {
      OPENAI_API_KEY     = var.openai_api_key,
      CREWAI_STORAGE_DIR = "/tmp/crewai",
      EMBEDCHAIN_DB_PATH = "/tmp/crewai/embedchain.db",
      HOME               = "/tmp"
    }
  }
}
