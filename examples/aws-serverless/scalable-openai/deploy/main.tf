# Scalable OpenAI Agent deployment using the updated serverless module
module "serverless_agents" {
  source = "yaalalabs/ak-serverless/aws"
  version = "0.3.0"

  # Basic configuration
  product_alias        = var.product_alias
  env_alias            = var.env_alias
  function_description = "Agent Kernel OpenAI Scalable Sample Lambda"
  function_name        = "request-handler"
  module_name          = var.module_name
  handler_path         = "lambda_request_handler.handler"
  package_path         = "../dist_request_handler.zip"
  package_type         = "LocalZip"
  memory_size          = 256
  timeout              = 45
  product_display_name = "AK OpenAI Scalable Serverless Example"
  region               = var.region
  is_production        = var.is_production

  # Execution mode - using for scalable processing
  queue_mode = true # recommended for production
  execution_mode = "rest_sync" # rest_sync or rest_async

  # Memory DB Config
  create_redis_cluster = true

  # Response Store Config 
  # create_redis_response_store = true # if True, it will use the memory Redis cluster for response store or may create.
  create_dynamodb_response_store = true

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
    module_name           = "agent-runner"
    function_name         = "ar-func"
    function_description  = "Agent runner for processing OpenAI requests"
    timeout               = 45
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
    function_name         = "response-handler"
    function_description  = "Response handler for processing completed requests"
    timeout               = 45
    memory_size           = 256
    handler_path          = "lambda_response_handler.handler"
    package_path          = "../dist_response_handler.zip"
  }

  # Queue configuration for scalable processing
  queue_config = {
    # Input queue settings
    input_queue_visibility_timeout = 60 # make sure to set it higher than the lambda timeout to avoid multiple processing of the same message
    input_queue_max_receive_count   = 3 
    input_queue_create_dlq          = false
    input_queue_message_retention_seconds = 300
    
    # Output queue settings  
    output_queue_visibility_timeout = 60 # make sure to set it higher than the lambda timeout to avoid multiple processing of the same message
    output_queue_max_receive_count   = 3
    output_queue_create_dlq          = false 
    output_queue_message_retention_seconds = 300
    
    # Processing settings
    batch_size                         = 10
    maximum_batching_window_in_seconds = 0
  }
} 