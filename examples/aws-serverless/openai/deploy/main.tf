# Lambda module configuration for deploying OpenAI Agent Lambda functions.
#
# Runs in queue_mode so the base deployment (which every other weekly-matrix example reuses the
# VPC/subnets and Lambda security groups of) creates and exposes all three per-tier security
# groups (request_handler/agent_runner/response_handler), not just the request handler's — see
# docs/specs/716-reuse-sg-in-integration-test-pipeline.
module "serverless_agents" {
  source  = "yaalalabs/ak-serverless/aws"
  version = "0.9.3"

  providers = { aws = aws, docker = docker }
  # Basic lambda configuration
  prefix               = var.prefix
  create_redis_cluster = true
  product_display_name = "AK OpenAI Serverless Example"
  region               = var.region
  is_production        = var.is_production

  # Execution mode
  queue_mode     = true
  execution_mode = "rest_sync"

  # Response Store Config - reuses the same Redis cluster created above
  create_redis_response_store = true

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

  # Request handler configuration
  request_handler = {
    function_name        = "openai-agents"
    function_description = "Agent Kernel OpenAI Sample Lambda — request ingress"
    handler_path         = "lambda_request_handler.handler"
    module_name          = "rqst-hdlr"
    package_path         = "../dist_request_handler"
    package_type         = "Image"
    memory_size          = 256
    environment_variables = {
      "OPENAI_API_KEY" = var.openai_api_key
    }
  }

  # Agent runner configuration
  agent_runner = {
    module_name          = "agent-runner"
    function_name        = "agent-runner"
    function_description = "Agent Kernel OpenAI Sample Lambda — agent execution"
    handler_path         = "lambda_agent_runner.handler"
    package_path         = "../dist_agent_runner"
    package_type         = "Image"
    memory_size          = 1024
    environment_variables = {
      "OPENAI_API_KEY" = var.openai_api_key
    }
  }

  # Response handler configuration
  response_handler = {
    module_name          = "rspns-hdlr"
    function_name        = "response-handler"
    function_description = "Agent Kernel OpenAI Sample Lambda — response storage"
    handler_path         = "lambda_response_handler.handler"
    package_path         = "../dist_response_handler"
    package_type         = "Image"
    memory_size          = 256
  }

  # Queue configuration
  queue_config = {
    input_queue_visibility_timeout        = 60
    input_queue_max_receive_count         = 3
    input_queue_create_dlq                = false
    input_queue_message_retention_seconds = 300

    output_queue_visibility_timeout        = 60
    output_queue_max_receive_count         = 3
    output_queue_create_dlq                = false
    output_queue_message_retention_seconds = 300

    batch_size                         = 10
    maximum_batching_window_in_seconds = 0
  }
}