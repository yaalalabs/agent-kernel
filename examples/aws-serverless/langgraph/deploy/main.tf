# Lambda module configuration for deploying OpenAI Agent Lambda function
module "serverless_agents" {
  source = "yaalalabs/ak-serverless/aws"
  version = "0.5.1"

  # Basic lambda configuration
  product_alias        = var.product_alias
  env_alias            = var.env_alias
  module_name          = var.module_name
  region               = var.region
  vpc_id               = var.vpc_id
  private_subnet_ids   = var.private_subnet_ids
  product_display_name = "AK Langraph Serverless Example"

  # Request handler configuration
  request_handler = {
    function_name         = "langgraph-agents"
    function_description   = "Agent Kernel LangGraph Sample Lambda"
    handler_path          = "lambda.handler"
    module_name           = var.module_name
    package_path          = "../dist"
    package_type          = "Image"
    memory_size           = 512
    environment_variables = {
      "OPENAI_API_KEY" = var.openai_api_key
    }
  }
}
