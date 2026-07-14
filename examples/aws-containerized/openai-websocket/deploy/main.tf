# Containerized module configuration for deploying OpenAI Agents in ECS, exposed over a
# WebSocket API (async execution mode, no SQS queue). The REST service container
# authenticates $connect, runs the agent inline on the chat route, and pushes the reply
# back over the connection itself — see ../README.md for the wire protocol.
module "containerized_agents" {
  source = "../../../../ak-deployment/ak-aws/containerized"

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
    image_uri      = var.ecr_image_uri
    environment_variables = {
      OPENAI_API_KEY = var.openai_api_key
    }
  }

  # WebSocket mode without a queue: the REST service handles $connect/$disconnect, runs the
  # agent inline for the chat route, and pushes the reply back over the connection.
  queue_mode     = false
  execution_mode = "async" # "async" (full reply) | "stream" (token-by-token)
  ws_chat_route  = "chat"

  # Custom WebSocket route beyond the default chat route — registered via
  # @AWSWebsocketAPI.register("status") in app.py.
  ws_routes = [
    { route = "status" }
  ]

  tags = {
    Example     = "openai-websocket"
    Environment = var.env_alias
  }
}
