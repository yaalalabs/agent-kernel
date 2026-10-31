# OpenAI Agents over WebSocket, queue-based token streaming — see ../README.md
module "containerized_agents" {
  source  = "yaalalabs/ak-containerized/aws"
  version = "0.9.5"

  providers = { aws = aws, docker = docker }

  prefix               = var.prefix
  container_type       = "ecs"
  region               = var.region
  vpc_id               = var.vpc_id
  private_subnet_ids   = var.private_subnet_ids
  product_display_name = "OpenAI Agents - WebSocket (Stream)"

  create_dynamodb_memory_table = true

  # Secret resolution: grants ssm:GetParameter on /ak/<prefix>/* and injects AK_SECRET__PREFIX, so the app
  # resolves OPENAI_API_KEY from /ak/<prefix>/<key lowercased> (config.yaml `secret:` block)
  # Terraform creates each parameter holding REPLACE_ME; overwrite it with the real value after the first apply.
  ssm_enabled     = true
  ssm_secret_keys = ["OPENAI_API_KEY"]

  # REST/IO service (ECSIOHandler): auth, enqueue chat, push chunks over the connection
  rest_service = {
    package_path = "../dist-rest-service"
    command      = ["python", "app_rest_service.py"]
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

  # Agent Runner: polls the Input Queue, fans out each streamed chunk to the Output Queue
  agent_runner = {
    cpu           = 1024
    memory        = 2048
    desired_count = 1
    package_path  = "../dist-agent-runner"
    command       = ["python", "app_agent_runner.py"]
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
    Example    = "openai-stream-queue-mode"
    Deployment = var.prefix
  }
}
