module "serverless_agents" {
  source  = "yaalalabs/ak-serverless/aws"
  version = "0.9.5"

  providers            = { aws = aws, docker = docker }
  prefix               = var.prefix
  product_display_name = "AK OpenAI Slack Serverless Example"
  region               = var.region
  is_production        = var.is_production
  vpc_id               = var.vpc_id
  private_subnet_ids   = var.private_subnet_ids
  queue_mode     = true
  execution_mode = "rest_async"
  create_dynamodb_memory_table   = true
  create_dynamodb_response_store = true

  api_version    = "v1"
  api_base_path  = "api"
  agent_endpoint = "chat"

  # Extra API Gateway route for Slack's Events API webhook, added alongside the
  # chat route the module always creates. It is served at
  # POST /<api_base_path>/<api_version>/slack/events and routed to the request
  # handler Lambda, which verifies the Slack signature and enqueues the message.
  # The path must match the @Lambda.register route in lambda_request_handler.py.
  # Set this URL as the Request URL in the Slack app's Event Subscriptions.
  # The authorizer bypasses this route (see lambda_auth.py), since Slack can't
  # send our bearer token.
  gateway_endpoints = [
    {
      path   = "/slack/events"
      method = "POST"
    },
  ]

  # ---- Authorizer ----
  authorizer = {
    description   = "Bearer-token auth for the chat route; lets Slack's webhook through"
    function_name = "gtwy-auth"
    handler_path  = "lambda_auth.handler"
    package_path  = "../dist_auth.zip"
    package_type  = "LocalZip"
    result_ttl_in_seconds = 0
    environment_variables = {
      "DEMO_AUTH_TOKEN" = var.demo_auth_token
    }
  }

  request_handler = {
    function_name        = "rqh-func"
    function_description = "Chat ingress and the Slack Events API webhook"
    handler_path         = "lambda_request_handler.handler"
    package_type         = "LocalZip"
    package_path         = "../dist_request_handler.zip"
    memory_size          = 512
    timeout              = 30
    security_group_id    = var.request_handler_security_group_id
    environment_variables = {
      "SLACK_BOT_TOKEN"      = var.slack_bot_token
      "SLACK_SIGNING_SECRET" = var.slack_signing_secret
    }
  }

  agent_runner = {
    function_name        = "ar-func"
    function_description = "Runs the agent for chat and Slack messages"
    timeout              = 45
    memory_size          = 1024
    handler_path         = "lambda_agent_runner.handler"
    package_type         = "Image"
    package_path         = "../dist_agent_runner"
    security_group_id    = var.agent_runner_security_group_id
    environment_variables = {
      "OPENAI_API_KEY" = var.openai_api_key
    }
  }

  response_handler = {
    function_name        = "rsh-func"
    function_description = "Delivers replies to Slack and to the response store"
    timeout              = 45
    memory_size          = 512
    handler_path         = "lambda_response_handler.handler"
    package_type         = "LocalZip"
    package_path         = "../dist_response_handler.zip"
    security_group_id    = var.response_handler_security_group_id
    environment_variables = {
      "SLACK_BOT_TOKEN"      = var.slack_bot_token
      "SLACK_SIGNING_SECRET" = var.slack_signing_secret
    }
  }

  # ---- Queue configuration ----
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
