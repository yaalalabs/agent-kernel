# Scalable OpenAI Agent deployment using the updated serverless module
module "serverless_agents" {
  source = "../../../../ak-deployment/ak-aws/serverless"

  # Basic configuration
  product_alias        = var.product_alias
  env_alias            = var.env_alias
  function_description = "Agent Kernel OpenAI Scalable Sample Lambda"
  function_name        = "openai-scalable-request-handler"
  handler_path         = "lambda_request_handler.handler"
  module_name          = var.module_name
  package_path         = "../dist_request_handler"
  package_type         = "Image"
  memory_size          = 256
  timeout              = 30
  product_display_name = "AK OpenAI Scalable Serverless Example"
  region               = var.region
  is_production        = var.is_production

  # Execution mode - using rest_async for scalable processing
  execution_mode = "rest_async"

  # Storage configuration
  create_redis_cluster = true
  create_redis_response_store = true

  # API Gateway configuration
  api_version    = "v1"
  api_base_path  = "api"
  agent_endpoint = "chat"

  # Custom API endpoints
  gateway_endpoints = [
    {
      path   = "app"
      method = "GET"
    },
    {
      path   = "app_info"
      method = "POST"
    }
  ]

  # Environment variables for request handler
  environment_variables = {
    "OPENAI_API_KEY" = var.openai_api_key
  }

  # Agent runner configuration
  agent_runner = {
    function_name         = "openai-scalable-agent-runner"
    function_description  = "Agent runner for processing OpenAI requests"
    timeout               = 300
    memory_size           = 512
    handler_path          = "lambda_agent_runner.handler"
    package_path          = "../dist_agent_runner"
    package_type          = "Image"
    environment_variables = {
      "OPENAI_API_KEY" = var.openai_api_key
    }
  }

  # Response handler configuration
  response_handler = {
    function_name         = "openai-scalable-response-handler"
    function_description  = "Response handler for processing completed requests"
    timeout               = 60
    memory_size           = 256
    handler_path          = "response_handler.handler"
  }

  # Queue configuration for scalable processing
  queue_config = {
    # Input queue settings
    input_queue_visibility_timeout = 330  # Should be >= agent_runner timeout + buffer
    input_queue_max_receive_count   = 3
    input_queue_create_dlq          = true
    
    # Output queue settings  
    output_queue_visibility_timeout = 90  # Should be >= response_handler timeout + buffer
    output_queue_max_receive_count   = 3
    output_queue_create_dlq          = true
    
    # Processing settings
    batch_size                         = 1
    maximum_batching_window_in_seconds = 0
  }

  # API Gateway Authorizer
  authorizer = {
    description           = "API Gateway Lambda Authorizer"
    function_name         = "openai-scalable-auth"
    handler_path          = "lambda_auth.handler"
    package_path          = "../dist_auth.zip"
    package_type          = "LocalZip"
    module_name           = "auth-scalable"
    result_ttl_in_seconds = 0
    environment_variables = {
      "SOME_OTHER_KEY" = "Some Other Value"
    }
  }
} 