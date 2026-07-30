# OpenAI Agents in ECS over a WebSocket API (async, no queue) — agent runs inline, reply pushed over the connection.
module "containerized_agents" {
  source = "yaalalabs/ak-containerized/aws"
  version = "0.7.0"

  product_alias        = var.product_alias
  env_alias            = var.env_alias
  module_name          = var.module_name
  container_type       = "ecs"
  region               = var.region
  vpc_id               = var.vpc_id
  private_subnet_ids   = var.private_subnet_ids
  product_display_name = "OpenAI Agents - WebSocket"

  create_dynamodb_memory_table = true

  rest_service = {
    package_path   = "../dist"
    container_port = 8000
    environment_variables = {
      OPENAI_API_KEY = var.openai_api_key
    }
  }

  # WebSocket without a queue: REST service handles connect/disconnect and runs the agent inline.
  queue_mode     = false
  execution_mode = "async" # "async" (full reply) | "stream" (token-by-token)
  ws_chat_route  = "chat"

  # Custom routes beyond chat — registered via @AWSWebsocketAPI.register(...) in app.py.
  ws_routes = [
    { route = "status" },
    { route = "echo" }
  ]

  tags = {
    Example     = "openai-websocket"
    Environment = var.env_alias
  }
}
