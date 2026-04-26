# Lambda module configuration for deploying OpenAI Agent Lambda function
module "serverless_agents" {
  source = "yaalalabs/ak-serverless/aws"
  version = "0.3.3"

  # Basic lambda configuration
  product_alias        = var.product_alias
  env_alias            = var.env_alias
  module_name          = var.module_name
  product_display_name = "AK OpenAI Auth Serverless Example"
  region               = var.region
  vpc_id               = "vpc-09033229d67314c1c"
  private_subnet_ids   = ["subnet-00e888e445f16d1b1", "subnet-0ab5240262cd77119"]

  # Request handler configuration
  request_handler = {
    function_name         = "openai-auth-agents"
    function_description   = "Agent Kernel OpenAI Auth Sample Lambda"
    handler_path          = "lambda.handler"
    module_name           = var.module_name
    package_path          = "../dist"
    package_type          = "Image"
    memory_size           = 256
    environment_variables = {
      "OPENAI_API_KEY" = var.openai_api_key
    }
  }

  # To override the default API version, API base path, and agent endpoint
  # api_version    = "0.3.3"
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
  
  # Defining the API Gateway Authorizer
  authorizer = {
    description           = "API Gateway Lambda Authorizer"
    function_name         = "gtwy-auth"
    handler_path          = "lambda_auth.handler"
    package_path          = "../dist_auth.zip"
    package_type          = "LocalZip"
    module_name           = "auth-eg"
    result_ttl_in_seconds = 0
    environment_variables = {
      "SOME_OTHER_KEY" = "Some Other Value"
    }
  }
} 