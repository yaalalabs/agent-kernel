# Lambda module configuration for deploying OpenAI Agent Lambda function
module "serverless_agents" {
  source = "yaalalabs/ak-serverless/aws"
  version = "0.4.0"

  # Basic lambda configuration
  product_alias        = var.product_alias
  env_alias            = var.env_alias
  module_name          = var.module_name
  create_redis_cluster = true
  product_display_name = "AK OpenAI Serverless Example"
  region               = var.region

  # Request handler configuration
  request_handler = {
    function_name         = "openai-agents"
    function_description   = "Agent Kernel OpenAI Sample Lambda"
    handler_path          = "lambda.handler"
    module_name           = var.module_name
    package_path          = "../dist"
    package_type          = "Image"
    memory_size           = 1024
    environment_variables = {
      "OPENAI_API_KEY" = var.openai_api_key
    }
  }

  # To override the default API version, API base path, and agent endpoint
  # api_version    = "v1"
  # api_base_path  = "api-new"
  # agent_endpoint = "chat-new"

  # Defining custom API endpoints
  gateway_endpoints = [
    {
      path           = "app",
      method         = "GET",
    },
    {
      path           = "app_info",
      method         = "POST",
    }
  ]
}