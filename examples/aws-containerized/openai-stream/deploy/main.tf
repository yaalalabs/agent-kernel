# OpenAI Agents over WebSocket, stream mode, no queue — agent runs inline
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
  # Terraform creates each parameter holding REPLACE_ME; overwrite it with the real value after the first apply.
  ssm_enabled     = true
  ssm_secret_keys = ["OPENAI_API_KEY"]

  rest_service = {
    package_path   = "../dist"
    container_port = 8000
  }

  # WebSocket without a queue: REST service handles connect/disconnect and runs the agent inline.
  queue_mode     = false
  execution_mode = "stream" # "async" (full reply) | "stream" (token-by-token)
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
