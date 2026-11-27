locals {
  # AWS Lambda Web Adapter layer (x86_64), pinned. It lives in the adapter's own account, per region.
  # https://github.com/awslabs/aws-lambda-web-adapter#lambda-functions-packaged-as-zip-package-for-aws-managed-runtimes
  lambda_adapter_layer_arn = "arn:aws:lambda:${var.region}:753240598075:layer:LambdaAdapterLayerX86:30"
}

# SSE (rest_sync + delta) OpenAI agent deployment on the serverless module
module "serverless_agents" {
  source  = "yaalalabs/ak-serverless/aws"
  version = "0.10.2"

  providers = { aws = aws, docker = docker }
  # Basic configuration
  prefix               = var.prefix
  product_display_name = "AK OpenAI SSE Serverless Example"
  region               = var.region
  is_production        = var.is_production
  vpc_id               = var.vpc_id
  private_subnet_ids   = var.private_subnet_ids

  # SSE needs the queue pipeline plus a response store that can stream chunks (Redis or Valkey)
  queue_mode     = true
  execution_mode = "rest_sync"
  message_type   = "delta"

  # The module creates the Redis cluster; its URL reaches every function that needs it
  create_redis_response_store = true

  # API Gateway configuration. The chat route is POST /api/v1/chat. There is no API Gateway authorizer in SSE
  # mode: the app authenticates callers through the `identity` block in config.yaml.
  api_version    = "v1"
  api_base_path  = "api"
  agent_endpoint = "chat"

  # Secret resolution: grants ssm:GetParameter on /ak/<prefix>/* and injects AK_SECRET__PREFIX, so the app
  # resolves OPENAI_API_KEY from /ak/<prefix>/<key lowercased> (config.yaml `secret:` block)
  ssm_enabled = true

  # Request handler: serves the SSE app through the Lambda Web Adapter. For a zip package the adapter is a layer
  # and handler_path names the start script.
  request_handler = {
    function_name        = "rqh-func"
    function_description = "Agent Kernel OpenAI SSE Sample Lambda"
    handler_path         = "run.sh"
    package_type         = "S3Zip"
    lambda_package_s3    = var.request_handler_lambda_package_s3
    layers               = [local.lambda_adapter_layer_arn]
    memory_size          = 512
    # The Lambda timeout bounds the stream (the gateway allows up to 15 minutes)
    timeout           = 300
    security_group_id = var.request_handler_security_group_id
    environment_variables = {
      # The credential of the static identity provider in config.yaml. Not needed with an oidc block.
      "DEMO_AUTH_TOKEN" = var.demo_auth_token
    }
  }

  # Agent runner configuration
  agent_runner = {
    function_name        = "ar-func"
    function_description = "Agent runner for processing OpenAI requests"
    timeout              = 45
    memory_size          = 512
    handler_path         = "lambda_agent_runner.handler"
    package_type         = "Image"
    ecr_image_uri        = var.agent_runner_ecr_image_uri
    security_group_id    = var.agent_runner_security_group_id
  }

  # Response handler configuration
  response_handler = {
    function_name        = "rsh-func"
    function_description = "Response handler: writes stream chunks to the response store"
    timeout              = 45
    memory_size          = 256
    handler_path         = "lambda_response_handler.handler"
    lambda_package_s3    = var.response_handler_lambda_package_s3
    package_type         = "S3Zip"
    security_group_id    = var.response_handler_security_group_id
  }

  # FIFO queues (the default) keep one session's chunks in order; SSE requires them
  queue_config = {
    fifo_queue = true

    input_queue_visibility_timeout        = 60 # higher than the runner timeout, to avoid processing a message twice
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
