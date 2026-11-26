module "serverless_agents" {
  source  = "yaalalabs/ak-serverless/aws"
  version = "0.10.2"

  providers            = { aws = aws, docker = docker }
  prefix               = var.prefix
  product_display_name = "AK A2A and MCP Serverless Example"
  region               = var.region
  is_production        = var.is_production
  vpc_id               = var.vpc_id
  private_subnet_ids   = var.private_subnet_ids

  # A2A and MCP need the queue pipeline (every call is enqueued) and a REST execution mode.
  queue_mode                     = true
  execution_mode                 = "rest_sync"
  create_dynamodb_memory_table   = true
  create_dynamodb_response_store = true

  api_version    = "v1"
  api_base_path  = "api"
  agent_endpoint = "chat"

  # Serve A2A and MCP: the API gateway gets /a2a, /a2a/{proxy+}, /mcp and /mcp/{proxy+}, all routed to the request
  # handler Lambda. They are the keys the application registers with Lambda.register
  # (ProtocolPaths.ROUTES in lambda_request_handler.py), so the flags and the code must agree.
  enable_a2a_server = true
  enable_mcp_server = true

  # ---- Authorizer ----
  # Bearer-token auth for the chat route. The A2A and MCP routes carry no authorizer: the request handler authenticates
  # them itself (config.yaml `identity`), as on ECS.
  authorizer = {
    description   = "Bearer-token auth for the chat route"
    function_name = "gtwy-auth"
    handler_path  = "lambda_auth.handler"
    package_path  = "../dist_auth.zip"
    package_type  = "LocalZip"
    environment_variables = {
      "DEMO_AUTH_TOKEN" = var.demo_auth_token
    }
  }

  # Secret resolution: grants ssm:GetParameter on /ak/<prefix>/* and injects AK_SECRET__PREFIX, so the agent runner
  # resolves OPENAI_API_KEY from /ak/<prefix>/openai_api_key (config.yaml `secret:` block)
  ssm_enabled = true

  # The request handler loads the agents (the A2A cards and the MCP tools are built from the registry at cold start),
  # so it deploys as an image with far more than the 128 MB default. Its timeout stays above API Gateway's 29 s: a
  # call waits for the agent's reply, at most (retry_count - 1) x delay = 18 s (config.yaml).
  request_handler = {
    function_name        = "rqh-func"
    function_description = "Chat ingress, A2A and MCP"
    handler_path         = "lambda_request_handler.handler"
    package_type         = "Image"
    package_path         = "../dist_request_handler"
    memory_size          = 2048
    timeout              = 30
    security_group_id    = var.request_handler_security_group_id
    environment_variables = merge(
      {
        # MCP and A2A authenticate the bearer token in this Lambda (see config.yaml `identity`).
        DEMO_AUTH_TOKEN = var.demo_auth_token
        # This Lambda registers the agents (the cards and tools are built from them) but never runs one, so it holds no
        # session: the agent runner owns them in DynamoDB. In queue mode the module gives this Lambda no session table, and
        # registering an agent builds the runtime's session store, which with config.yaml's `dynamodb` would fail at start.
        AK_SESSION__TYPE = "in_memory"
      },
      # a2a.url and mcp.url: public, stage and base path included. Empty on the first apply (the API does not exist yet).
      var.public_base_url == "" ? {} : {
        AK_A2A__URL = "${var.public_base_url}/a2a"
        AK_MCP__URL = "${var.public_base_url}/mcp"
      },
    )
  }

  agent_runner = {
    function_name        = "ar-func"
    function_description = "Runs the agent for chat, A2A and MCP"
    timeout              = 45
    memory_size          = 1024
    handler_path         = "lambda_agent_runner.handler"
    package_type         = "Image"
    package_path         = "../dist_agent_runner"
    security_group_id    = var.agent_runner_security_group_id
  }

  response_handler = {
    function_name        = "rsh-func"
    function_description = "Stores each reply for the caller waiting on it"
    timeout              = 45
    memory_size          = 512
    handler_path         = "lambda_response_handler.handler"
    package_type         = "LocalZip"
    package_path         = "../dist_response_handler.zip"
    security_group_id    = var.response_handler_security_group_id
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
