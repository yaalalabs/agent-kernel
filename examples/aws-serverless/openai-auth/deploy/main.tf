# Lambda module configuration for deploying OpenAI Agent Lambda function
module "serverless_agents" {
  source = "yaalalabs/ak-serverless/aws"
  version = "0.2.11"

  # Basic lambda configuration
  product_alias        = var.product_alias
  env_alias            = var.env_alias
  function_description = "Agent Kernel OpenAI Auth Sample Lambda"
  function_name        = "openai-auth-agents"
  handler_path         = "lambda.handler"
  module_name          = var.module_name
  package_path         = "../dist"
  package_type         = "Image"
  memory_size          = 256
  create_redis_cluster = true
  product_display_name = "AK OpenAI Auth Serverless Example"
  region               = var.region

  # To override the default API version, API base path, and agent endpoint
  # api_version    = "v2"
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

  # Environment variables passed to lambda
  environment_variables = {
    "OPENAI_API_KEY" = var.openai_api_key
  }
  
  # Defining the API Gateway Authorizer
  authorizer_function_description = "API Gateway Lambda Authorizer"
  authorizer_function_name = "gtwy-auth"
  authorizer_handler_path = "lambda.handler"
  authorizer_package_path = "../auth_deployment/auth_dist.zip"
  authorizer_package_type = "LocalZip"
  authorizer_module_name = var.authorizer_module_name
  authorizer_result_ttl_in_seconds = 0
  authorizer_environment_variables = {
    "SOME_OTHER_KEY" = "Some Other Value"
  }
} 