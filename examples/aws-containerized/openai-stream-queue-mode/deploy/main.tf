# OpenAI Agents in ECS over a WebSocket API with queue-based, token-streaming processing — see ../README.md.
module "containerized_agents" {
  source = "yaalalabs/ak-containerized/aws"
  version = "0.8.0"

  product_alias        = var.product_alias
  env_alias            = var.env_alias
  module_name          = var.module_name
  container_type       = "ecs"
  region               = var.region
  vpc_id               = var.vpc_id
  private_subnet_ids   = var.private_subnet_ids
  product_display_name = "OpenAI Agents - WebSocket (Stream)"

  create_dynamodb_memory_table = true

  # REST/IO service: authenticates $connect, enqueues chat, and pushes streamed chunks back over the connection (ECSIOHandler).
  rest_service = {
    package_path = "../dist-rest-service"
    command      = ["python", "app_rest_service.py"]
    environment_variables = {
      OPENAI_API_KEY = var.openai_api_key
    }
  }

  # Queue mode + WebSocket, STREAM execution mode
  queue_mode     = true
  execution_mode = "stream" # each token delta is pushed as its own STREAM_CHUNK message
  ws_chat_route  = "chat"

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

  # Agent Runner: separate ECS service that polls the Input Queue, runs the agent, and fans out
  # each streamed chunk as its own message on the Output Queue (agentkernel.aws.ECSAgentRunner
  # resolves to ECSStreamAgentRunner because config.yaml sets execution.mode: stream).
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

  # Agent Runner auto scaling: scale on SQS backlog per task (BacklogPerTask metric).
  scaling_config = {
    enabled            = true
    min_count          = 1
    max_count          = 10
    backlog_target     = 10
    scale_in_cooldown  = 120
    scale_out_cooldown = 30
  }

  tags = {
    Example     = "openai-stream"
    Environment = var.env_alias
  }
}
