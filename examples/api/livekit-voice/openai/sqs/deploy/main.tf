module "containerized_agents" {
  source  = "yaalalabs/ak-containerized/aws"
  version = "0.9.3"

  providers = { aws = aws, docker = docker }

  prefix               = var.prefix
  container_type       = "ecs"
  region               = var.region
  vpc_id               = var.vpc_id
  private_subnet_ids   = var.private_subnet_ids
  product_display_name = "LiveKit Voice (SQS Scalable)"

  # IO Service (LiveKit Gateway): Connects out to LiveKit Cloud, pushes mic audio to SQS input queue.
  rest_service = {
    package_path = "../dist-livekit-io"
    command      = ["python", "app_livekit_io.py"]
    environment_variables = {
      LIVEKIT_URL        = var.livekit_url
      LIVEKIT_API_KEY    = var.livekit_api_key
      LIVEKIT_API_SECRET = var.livekit_api_secret
    }
  }

  queue_mode     = true
  execution_mode = "async"

  queue_config = {
    input_queue_visibility_timeout        = 120
    input_queue_message_retention_seconds = 1800
    input_queue_max_receive_count         = 4
    input_queue_create_dlq                = true

    output_queue_visibility_timeout        = 60
    output_queue_message_retention_seconds = 1800
    output_queue_max_receive_count         = 4
    output_queue_create_dlq                = true
  }

  # Agent Runner: separate ECS service that polls the Input Queue, runs the agent via OpenAI Realtime WebSocket, sends results to Output Queue.
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

  scaling_config = {
    enabled            = true
    min_count          = 1
    max_count          = 10
    backlog_target     = 10
    scale_in_cooldown  = 120
    scale_out_cooldown = 30
  }

  enable_api_gateway_logs = false

  tags = {
    Example    = "livekit-voice-sqs"
    Deployment = var.prefix
  }
}
