# Containerized module configuration for deploying OpenAI Agents in ECS, exposed over a
# WebSocket API with queue-based (scalable) processing:
#   Client -> WS API Gateway -> REST/IO service ($connect / enqueue chat) -> Input Queue
#         -> Agent Runner (scales on backlog) -> Output Queue
#         -> REST/IO service's output-queue consumer -> pushed back over the WS connection
# See ../README.md for the wire protocol and architecture.
module "containerized_agents" {
  # Containerized WebSocket mode is not yet published to the `yaalalabs/ak-containerized/aws`
  # registry module — pin to the local source until a release picks it up, then switch to:
  #   source  = "yaalalabs/ak-containerized/aws"
  #   version = "<next release>"
  source = "../../../../ak-deployment/ak-aws/containerized"

  product_alias        = var.product_alias
  env_alias            = var.env_alias
  module_name          = var.module_name
  container_type       = "ecs"
  region               = var.region
  vpc_id               = var.vpc_id
  private_subnet_ids   = var.private_subnet_ids
  product_display_name = "OpenAI Agents - WebSocket (Scalable)"

  create_dynamodb_memory_table = true

  # ---- REST/IO Service ----
  # Authenticates $connect, enqueues chat frames, and pushes agent replies back over the
  # WebSocket connection (Thread 2 polls the Output Queue — see ECSIOHandler).
  rest_service = {
    package_path = "../dist-rest-service"
    command      = ["python", "app_rest_service.py"]
    environment_variables = {
      OPENAI_API_KEY = var.openai_api_key
    }
  }

  # ---- Queue mode + WebSocket ----
  queue_mode     = true
  execution_mode = "async" # only "async" is wired up end-to-end today; "stream" isn't yet implemented for ECS
  ws_chat_route  = "chat"

  # Custom WebSocket route beyond the default chat route — registered via
  # @AWSWebsocketAPI.register("status") in app_rest_service.py, answered directly (no queue involved).
  ws_routes = [
    { route = "status" }
  ]

  queue_config = {
    input_queue_visibility_timeout        = 120 # should be >= agent processing time
    input_queue_message_retention_seconds = 1800
    input_queue_max_receive_count         = 4
    input_queue_create_dlq                = true

    output_queue_visibility_timeout        = 60
    output_queue_message_retention_seconds = 1800
    output_queue_max_receive_count         = 4
    output_queue_create_dlq                = true
  }

  # ---- Agent Runner ----
  # Separate ECS service that polls the Input Queue, runs the agent, and sends the result
  # (with the endpoint_url forwarded) to the Output Queue.
  agent_runner = {
    cpu           = 1024
    memory        = 2048
    desired_count = 1
    package_path  = "../dist-agent-runner"
    command       = ["python", "app_agent_runner.py"]
    environment_variables = {
      OPENAI_API_KEY = var.openai_api_key
    }
  }

  # ---- Agent Runner Auto Scaling ----
  # Scale based on SQS backlog per task (BacklogPerTask custom metric).
  scaling_config = {
    enabled            = true
    min_count          = 1
    max_count          = 10
    backlog_target     = 10
    scale_in_cooldown  = 120
    scale_out_cooldown = 30
  }

  tags = {
    Example     = "openai-websocket-scalable"
    Environment = var.env_alias
  }
}
