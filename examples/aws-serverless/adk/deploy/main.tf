# Lambda module configuration for deploying Google Agent Lambda function
module "serverless_agents" {
  source  = "yaalalabs/ak-serverless/aws"
  version = "0.9.1"

  providers = { aws = aws, docker = docker }
  # Basic lambda configuration
  prefix               = var.prefix
  region               = var.region
  vpc_id               = var.vpc_id
  private_subnet_ids   = var.private_subnet_ids
  product_display_name = "AK Google ADK Serverless Example"

  # Request handler configuration
  request_handler = {
    function_name        = "adk-agents"
    function_description = "Agent Kernel ADK Sample Lambda"
    handler_path         = "lambda.handler"
    package_path         = "../dist"
    package_type         = "Image"
    memory_size          = 1024
    timeout              = 60
    environment_variables = {
      OPENAI_API_KEY = var.openai_api_key,
    }
  }
}
