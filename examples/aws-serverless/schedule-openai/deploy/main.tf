# ---------------------------------------------------------------------------
# Serverless Agents Deployment — scheduled and recurring chats
# ---------------------------------------------------------------------------
module "serverless_agents" {
  source  = "yaalalabs/ak-serverless/aws"
  version = "0.8.1"

  providers            = { aws = aws, docker = docker }
  product_alias        = var.product_alias
  env_alias            = var.env_alias
  module_name          = var.module_name
  product_display_name = "AK OpenAI Scheduled Chats Serverless Example"
  region               = var.region
  is_production        = var.is_production
  vpc_id               = var.vpc_id
  private_subnet_ids   = var.private_subnet_ids

  # ---- Queue Mode ----
  # Mandatory for scheduling: EventBridge Scheduler delivers each occurrence to the Input Queue.
  queue_mode     = true
  execution_mode = "rest_sync"

  # ---- Stores ----
  create_dynamodb_memory_table   = true
  create_dynamodb_response_store = true

  # ---- Scheduling ----
  # enable_scheduling provisions the EventBridge Scheduler schedule group and the execution role
  # Scheduler assumes to send triggers to the Input Queue, grants both Lambda roles
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

  # ---- API Gateway configuration ----
  api_version    = "v1"
  api_base_path  = "api"
  agent_endpoint = "chat"

  # The gateway only proxies paths registered here. These map to the `Lambda.register` routes in
  # lambda_request_handler.py. The serverless router matches paths exactly, so there are no
  # `{task_id}` path parameters — the task id travels as a query parameter or in the body.
  gateway_endpoints = [
    {
      path   = "schedules"
      method = "GET" # list
    },
    {
      path   = "schedules/get"
      method = "GET" # read one
    },
    {
      path   = "schedules/amend"
      method = "POST" # full-replacement amendment
    },
    {
      path   = "schedules/cancel"
      method = "POST" # cancel
    },
  ]

  # ---- Request handler ----
  # Chat ingress plus the custom schedule management routes.
  request_handler = {
    module_name          = "rqst-hdlr"
    function_name        = "rqh-func"
    function_description = "Chat ingress and scheduled-task management routes"
    handler_path         = "lambda_request_handler.handler"
    package_type         = "LocalZip"
    package_path         = "../dist_request_handler.zip"
    memory_size          = 256
    timeout              = 45
    environment_variables = {
      "OPENAI_API_KEY" = var.openai_api_key
    }
  }

  # ---- Agent runner ----
  # Runs fired occurrences and hosts the create_schedule/update_schedule/delete_schedule tools.
  # Image mode: agentkernel[aws,openai,schedule] carries the OpenAI Agents SDK and does not fit
  # inside Lambda's 250 MB unzipped zip limit. Terraform builds ../dist_agent_runner (deps under
  # data/ plus the Dockerfile deploy.sh copies in) and pushes it to an ECR repository it creates.
  agent_runner = {
    module_name          = "agent-runner"
    function_name        = "ar-func"
    function_description = "Runs scheduled occurrences and registers new tasks"
    timeout              = 45
    memory_size          = 1024
    handler_path         = "lambda_agent_runner.handler"
    package_type         = "Image"
    package_path         = "../dist_agent_runner"
    environment_variables = {
      "OPENAI_API_KEY" = var.openai_api_key
    }
  }

  # ---- Response handler ----
  response_handler = {
    function_name        = "rsh-func"
    module_name          = "rspns-hdlr"
    function_description = "Writes completed responses to the response store"
    timeout              = 45
    memory_size          = 256
    handler_path         = "lambda_response_handler.handler"
    package_type         = "LocalZip"
    package_path         = "../dist_response_handler.zip"
  }

  # ---- Queue configuration ----
  queue_config = {
    # Keep visibility timeouts >= the consuming Lambda's timeout, or a message is redelivered
    # while it is still being processed.
    input_queue_visibility_timeout        = 60
    input_queue_max_receive_count         = 3
    input_queue_create_dlq                = false
    input_queue_message_retention_seconds = 300

    output_queue_visibility_timeout        = 60
    output_queue_max_receive_count         = 3
    output_queue_create_dlq                = false
    output_queue_message_retention_seconds = 300

    batch_size                         = 10
    maximum_batching_window_in_seconds = 0
  }
}
