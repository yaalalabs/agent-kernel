# Lambda module configuration for deploying OpenAI Agent Lambda function
module "serverless_agents" {
  source  = "yaalalabs/ak-serverless/aws"
  version = "0.9.2"

  providers = { aws = aws, docker = docker }
  # Basic lambda configuration
  prefix               = var.prefix
  product_display_name = "AK OpenAI Auth Serverless Example"
  region               = var.region
  vpc_id               = var.vpc_id
  private_subnet_ids   = var.private_subnet_ids

  # Memory DB Config - use existing Redis cluster
  create_redis_cluster = false

  # Request handler configuration
  request_handler = {
    function_name        = "openai-auth-agents"
    function_description = "Agent Kernel OpenAI Auth Sample Lambda"
    handler_path         = "lambda.handler"
    package_path         = "../dist"
    package_type         = "Image"
    memory_size          = 256
    security_group_id    = var.request_handler_security_group_id
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
      path   = "app",
      method = "GET",
    },
    {
      path   = "app_info",
      method = "POST",
    }
  ]

  # Defining the API Gateway Authorizer
  authorizer = {
    description           = "API Gateway Lambda Authorizer"
    function_name         = "gtwy-auth"
    handler_path          = "lambda_auth.handler"
    package_path          = "../dist_auth.zip"
    package_type          = "LocalZip"
    result_ttl_in_seconds = 0
    environment_variables = {
      "SOME_OTHER_KEY" = "Some Other Value"
    }
  }
} 