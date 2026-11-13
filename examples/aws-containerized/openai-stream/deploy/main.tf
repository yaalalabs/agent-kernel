# OpenAI Agents over WebSocket, async + delta (token streaming), no queue — agent runs inline
module "containerized_agents" {
  source  = "yaalalabs/ak-containerized/aws"
  version = "0.9.5"

  providers = { aws = aws, docker = docker }

  prefix               = var.prefix
  container_type       = "ecs"
  region               = var.region
  vpc_id               = var.vpc_id
  private_subnet_ids   = var.private_subnet_ids
  product_display_name = "OpenAI Agents - WebSocket (Stream, Direct)"

  create_dynamodb_memory_table = true

  # Secret resolution: grants ssm:GetParameter on /ak/<prefix>/* and injects AK_SECRET__PREFIX, so the app
  # resolves OPENAI_API_KEY from /ak/<prefix>/<key lowercased> (config.yaml `secret:` block)
  ssm_enabled = true

  rest_service = {
    package_path   = "../dist"
    container_port = 8000
    environment_variables = {
      DEMO_AUTH_TOKEN = var.demo_auth_token
    }
  }

  # WebSocket without a queue: REST service handles connect/disconnect and runs the agent inline.
  queue_mode     = false
  execution_mode = "async"
  message_type   = "delta" # "complete" (full reply) | "delta" (token-by-token)
  ws_chat_route  = "chat"

  # Custom routes beyond chat — registered via @AWSWebsocketAPI.register(...) in app.py.
  ws_routes = [
    { route = "status" },
    { route = "echo" }
  ]

  tags = {
    Example    = "openai-stream"
    Deployment = var.prefix
  }
}
