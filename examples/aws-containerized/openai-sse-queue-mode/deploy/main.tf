# OpenAI Agents over SSE, queue-based token streaming — see ../README.md
module "containerized_agents" {
  source  = "yaalalabs/ak-containerized/aws"
  version = "0.10.2"

  providers = { aws = aws, docker = docker }

  prefix               = var.prefix
  container_type       = "ecs"
  region               = var.region
  vpc_id               = var.vpc_id
  private_subnet_ids   = var.private_subnet_ids
  product_display_name = "OpenAI Agents - SSE (Stream)"

  create_dynamodb_memory_table = true

  # No per-deployment cluster: config.yaml points the response store at the long-lived shared
  # examples cluster in the base VPC, as every other CI-tested example does. `terraform plan` warns
  # that SSE needs a streaming store and sees no module cluster; that warning is expected here, and
  # the external URL is what satisfies the requirement.
  create_redis_cluster = false

  # Secret resolution: grants ssm:GetParameter on /ak/<prefix>/* and injects AK_SECRET__PREFIX, so the app
  # resolves OPENAI_API_KEY from /ak/<prefix>/<key lowercased> (config.yaml `secret:` block)
  ssm_enabled = true

  # REST/IO service (IOHandler): serves the chat route, enqueues the request, then streams the
  # reply chunks back out of the response store as text/event-stream.
  rest_service = {
    alb_security_group_id         = var.alb_security_group_id
    ecs_service_security_group_id = var.ecs_service_security_group_id
    package_path                  = "../dist-rest-service"
    cpu                           = 256
    memory                        = 512
    desired_count                 = 1
    container_port                = 8000
    health_check_endpoint         = "/health"
    command                       = ["python", "app_rest_service.py"]
  }

  # Queue mode + SSE: rest_sync holds the request open, delta makes the reply chunked.
  queue_mode     = true
  execution_mode = "rest_sync"
  message_type   = "delta"

  # A stream is bounded by two independent caps, so both are raised here for the measurement runs.
  # alb_idle_timeout bounds a silent gap between chunks; gateway_integration_timeout bounds the
  # stream's total length. Raising one does not extend what the other is cutting.
  alb_idle_timeout            = 900
  gateway_integration_timeout = 900

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
    security_group_id = var.agent_runner_security_group_id
    cpu               = 1024
    memory            = 2048
    desired_count     = 1
    package_path      = "../dist-agent-runner"
    command           = ["python", "app_agent_runner.py"]
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
    Example    = "openai-sse-queue-mode"
    Deployment = var.prefix
  }
}
