# Queue mode: the request handler enqueues each /chat request, the agent runner runs the agent (and sends its
# Langfuse traces), and the response handler stores the reply. The request handler also serves /eval and /check
# and runs the grading in an asynchronous self-invocation.
module "serverless_agents" {
  source  = "yaalalabs/ak-serverless/aws"
  version = "0.9.5"

  providers            = { aws = aws, docker = docker }
  prefix               = var.prefix
  region               = var.region
  is_production        = var.is_production
  vpc_id               = var.vpc_id
  private_subnet_ids   = var.private_subnet_ids
  product_display_name = "AK OpenAI Langfuse Trace Evaluation Serverless Example"

  queue_mode     = true
  execution_mode = "rest_sync"

  # Session and response stores use the base deployment's Redis cluster (config.yaml)
  create_redis_cluster        = false
  create_redis_response_store = false

  # POST /api/v1/eval starts grading a session; GET /api/v1/check reports its progress
  gateway_endpoints = [
    { path = "eval", method = "POST" },
    { path = "check", method = "GET" },
  ]

  request_handler = {
    function_name        = "trace-eval-rqh"
    function_description = "Agent Kernel OpenAI Langfuse trace evaluation example: ingress, /eval, /check and grading"
    handler_path         = "lambda_request_handler.handler"
    package_path         = "../dist_request_handler"
    package_type         = "Image"
    timeout              = 600  # 10 minutes for the grading invocation; the 45 s default is too short for the judges
    memory_size          = 1024 # the 128 MB default is too small for Opik and litellm
    security_group_id    = var.request_handler_security_group_id
    environment_variables = {
      OPENAI_API_KEY         = var.openai_api_key # the judges
      LANGFUSE_PUBLIC_KEY    = var.langfuse_public_key
      LANGFUSE_SECRET_KEY    = var.langfuse_secret_key
      LANGFUSE_BASE_URL      = var.langfuse_base_url
      AK_TEST__LLM__PROVIDER = "openai"
      AK_TEST__LLM__MODEL    = "gpt-4.1-mini"
      OPIK_TRACK_DISABLE     = "true"
      RESULTS_TABLE          = aws_dynamodb_table.results.name
    }
  }

  agent_runner = {
    function_name        = "trace-eval-ar"
    function_description = "Agent Kernel OpenAI Langfuse trace evaluation example: agent execution"
    handler_path         = "lambda_agent_runner.handler"
    package_path         = "../dist_agent_runner"
    package_type         = "Image"
    memory_size          = 1024
    security_group_id    = var.agent_runner_security_group_id
    environment_variables = {
      OPENAI_API_KEY      = var.openai_api_key
      LANGFUSE_PUBLIC_KEY = var.langfuse_public_key
      LANGFUSE_SECRET_KEY = var.langfuse_secret_key
      LANGFUSE_BASE_URL   = var.langfuse_base_url
    }
  }

  response_handler = {
    function_name        = "trace-eval-rsh"
    function_description = "Agent Kernel OpenAI Langfuse trace evaluation example: response storage"
    handler_path         = "lambda_response_handler.handler"
    package_type         = "LocalZip"
    package_path         = "../dist_response_handler.zip"
    memory_size          = 256
    security_group_id    = var.response_handler_security_group_id
  }

  queue_config = {
    input_queue_visibility_timeout        = 60 # above the agent runner's 45 s timeout, so a message isn't processed twice
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

# One row per trace: its grading progress, its summary and, once graded, one column per metric
resource "aws_dynamodb_table" "results" {
  name         = "${var.prefix}-trace-evaluations"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "trace_id"

  attribute {
    name = "trace_id"
    type = "S"
  }

  attribute {
    name = "session_id"
    type = "S"
  }

  global_secondary_index {
    name               = "session_id-index"
    hash_key           = "session_id"
    projection_type    = "INCLUDE" # /check reads only these; ALL would copy every row's spans_gz
    non_key_attributes = ["progress", "error", "updated_at"]
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }
}

# The module creates the role; the example only adds the table permissions. The self-invoke needs no
# statement: the module already attaches AWSLambdaRole to the request handler's role.
resource "aws_iam_role_policy" "evaluation" {
  name = "${var.prefix}-trace-evaluation"
  role = module.serverless_agents.request_handler_lambda_role_name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:BatchGetItem", "dynamodb:Query"]
        Resource = [aws_dynamodb_table.results.arn, "${aws_dynamodb_table.results.arn}/index/*"]
      },
    ]
  })
}

# No automatic retry of the grading invocation (a request-handler self-invoke): the next /eval re-queues a killed grading
resource "aws_lambda_function_event_invoke_config" "grading" {
  function_name          = module.serverless_agents.request_handler_lambda_function_name
  maximum_retry_attempts = 0
}
