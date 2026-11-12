locals {
  # The credentials of the static identity provider in config.yaml. Not needed with an oidc block.
  # Bob's is derived from alice's so one generated value (CI's TF_VAR_demo_auth_token) serves both.
  demo_credentials = {
    "ALICE_TOKEN" = var.demo_auth_token
    "BOB_TOKEN"   = "${var.demo_auth_token}-bob"
  }
}

module "serverless_agents" {
  source  = "yaalalabs/ak-serverless/aws"
  version = "0.9.5"

  providers            = { aws = aws, docker = docker }
  prefix               = var.prefix
  product_display_name = "AK OpenAI Thread Serverless Example"
  region               = var.region
  is_production        = var.is_production
  vpc_id               = var.vpc_id
  private_subnet_ids   = var.private_subnet_ids

  # Threads on Lambda run in queue mode only: the request handler records the user message before
  # enqueueing, and the agent runner records the reply.
  queue_mode                     = true
  execution_mode                 = "rest_sync"
  create_dynamodb_memory_table   = true
  create_dynamodb_response_store = true
  # One thread table, wired into the request handler (user message, read routes) and the agent
  # runner (reply). config.yaml's `thread.type: dynamodb` selects it.
  create_dynamodb_thread_table = true

  api_version    = "v1"
  api_base_path  = "api"
  agent_endpoint = "chat"

  # The thread read routes, added alongside the chat route the module always creates. They are
  # served at GET /<api_base_path>/<api_version>/threads[/{session_id}] and must match the
  # @Lambda.register routes in lambda_request_handler.py.
  gateway_endpoints = [
    {
      path   = "/threads"
      method = "GET"
    },
    {
      path   = "/threads/{session_id}"
      method = "GET"
    },
  ]

  # The authorizer runs on every route: it validates the bearer token through the identity block
  # in config.yaml (lambda_auth.py is one line) and hands the principal to the request handler,
  # which records threads under it and scopes the read routes to it.
  authorizer = {
    description           = "Bearer-token auth through the identity provider in config.yaml"
    function_name         = "gtwy-auth"
    handler_path          = "lambda_auth.handler"
    package_path          = "../dist_auth.zip"
    package_type          = "LocalZip"
    result_ttl_in_seconds = 0
    environment_variables = local.demo_credentials
  }

  # An image, not a zip: the thread extra (LiteLLM, for thread naming) does not fit in a Lambda zip.
  request_handler = {
    function_name        = "rqh-func"
    function_description = "Chat ingress with thread recording, and the thread read routes"
    handler_path         = "lambda_request_handler.handler"
    package_type         = "Image"
    package_path         = "../dist_request_handler"
    memory_size          = 1024
    timeout              = 30
    security_group_id    = var.request_handler_security_group_id
    # The credentials too: ThreadRequestHandler() builds the identity provider config.yaml names,
    # and the static provider resolves them at startup, though only the authorizer authenticates.
    environment_variables = merge(local.demo_credentials, {
      # For thread naming (LiteLLM); without it the name falls back to the prompt prefix.
      "OPENAI_API_KEY" = var.openai_api_key
    })
  }

  agent_runner = {
    function_name        = "ar-func"
    function_description = "Runs the agent and records the reply in the thread"
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
    function_description = "Writes replies to the response store"
    timeout              = 45
    memory_size          = 512
    handler_path         = "lambda_response_handler.handler"
    package_type         = "LocalZip"
    package_path         = "../dist_response_handler.zip"
    security_group_id    = var.response_handler_security_group_id
  }

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
