# ---------------------------------------------------------------------------
# Containerized Agents Deployment — scheduled and recurring chats
# ---------------------------------------------------------------------------
module "containerized_agents" {
  source  = "yaalalabs/ak-containerized/aws"
  version = "0.8.1"

  providers            = { aws = aws, docker = docker }
  product_alias        = var.product_alias
  env_alias            = var.env_alias
  module_name          = var.module_name
  region               = var.region
  product_display_name = "OpenAI Agents - Scheduled Chats"

  vpc_id             = var.vpc_id
  private_subnet_ids = var.private_subnet_ids

  # ---- REST Service Configuration ----
  # Serves chat ingress (enqueue + poll) and the schedule management routes.
  rest_service = {
    package_path          = "../dist-rest-service"
    cpu                   = 256
    memory                = 512
    desired_count         = 1
    container_port        = 8000
    health_check_endpoint = "/health"
    command               = ["python", "app_rest_service.py"]
    environment_variables = {
      OPENAI_API_KEY = var.openai_api_key
    }
  }

  # ---- Agent Memory (Session Store) ----
  create_dynamodb_memory_table = true

  # ---- Queue Mode ----
  # Mandatory for scheduling: EventBridge Scheduler delivers each occurrence to the Input Queue.
  queue_mode     = true
  execution_mode = "rest_sync"

  # ---- Scheduling ----
  # enable_scheduling provisions the EventBridge Scheduler schedule group and the execution role
  # Scheduler assumes to send triggers to the Input Queue, grants both task roles
  # scheduler:*Schedule + iam:PassRole on them, injects the three
  # AK_SCHEDULE__PROVIDER__EVENTBRIDGE__* variables, and flips the Input Queue to
  # content-based deduplication (Scheduler cannot set a MessageDeduplicationId).
  #
  # create_dynamodb_schedule_table provisions the task store (partition task_id, no sort key) and
  # injects AK_SCHEDULE__STORE__DYNAMODB__TABLE_NAME.
  #
  # Neither flag injects a `type` — config.yaml declares
  # `schedule.provider.type: eventbridge` and `schedule.store.type: dynamodb`.
  enable_scheduling              = true
  create_dynamodb_schedule_table = true

  # ---- API Gateway routes ----
  # The gateway only proxies paths registered here. The chat route is added by the module; the
  # schedule management routes must be declared. `overwrite_path` is the backend path the ALB is
  # given: it is required and must be non-empty, so each route maps onto *itself* — FastAPI has to
  # see the real /api/v1/schedules... path that ScheduleRESTRequestHandler declares.
  # $request.path.task_id is an API Gateway parameter-mapping expression that carries the path
  # parameter through unchanged.
  api_version    = "v1"
  api_base_path  = "api"
  agent_endpoint = "chat"

  gateway_endpoints = [
    {
      path           = "schedules"
      method         = "ANY" # GET (list)
      overwrite_path = "/api/v1/schedules"
    },
    {
      path           = "schedules/{task_id}"
      method         = "ANY" # GET (read), PUT (amend), DELETE (cancel)
      overwrite_path = "/api/v1/schedules/$request.path.task_id"
    },
  ]

  # ---- Queue Configuration ----
  queue_config = {
    input_queue_visibility_timeout        = 120 # >= agent processing time
    input_queue_message_retention_seconds = 1800
    input_queue_max_receive_count         = 3
    input_queue_create_dlq                = true

    output_queue_visibility_timeout        = 60
    output_queue_message_retention_seconds = 1800
    output_queue_max_receive_count         = 3
    output_queue_create_dlq                = true

    sqs_managed_sse_enabled   = true
    max_message_size          = 262144
    receive_wait_time_seconds = 0
  }

  # ---- Agent Runner Configuration ----
  # Runs fired occurrences and hosts the create_schedule/update_schedule/delete_schedule tools.
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
  scaling_config = {
    enabled            = true
    min_count          = 1
    max_count          = 10
    backlog_target     = 10
    scale_in_cooldown  = 120
    scale_out_cooldown = 30
  }

  tags = {
    Example     = "openai-schedule"
    Environment = var.env_alias
  }
}
