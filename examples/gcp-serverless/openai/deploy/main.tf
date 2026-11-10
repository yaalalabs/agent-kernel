# Cloud Run (serverless) module configuration for deploying OpenAI Agent.
# The serverless module uses Cloud Run with min_instance_count = 0 (scale-to-zero),
# which is the GCP equivalent of AWS Lambda Image type deployment.
# This example exposes the following endpoints via API Gateway:
# /api/v1/chat            - Agent execution
# /api/v1/chat-multipart  - Agent execution with file uploads
# /api/v1/app             - Custom GET endpoint
# /api/v1/app_info        - Custom POST endpoint
module "serverless_agents" {
  source  = "yaalalabs/ak-serverless/google"
  version = "0.9.5"

  providers = { google = google, google-beta = google-beta, docker = docker }
  # Basic Cloud Run configuration
  project_id   = var.project_id
  prefix       = var.prefix
  package_path = "../dist"
  # A request waits for its reply, which includes a cold start of the runner after a quiet spell.
  # config.yaml's response store waits up to 100 s, inside this 110 s gateway deadline.
  timeout              = 120
  backend_deadline     = 110
  memory               = "512Mi"
  create_redis_cluster = true
  product_display_name = "AK OpenAI Serverless Example"
  region               = var.region
  container_port       = 8000

  # To override the default API version, API base path, and agent endpoint:
  # api_version    = "v2"
  # api_base_path  = "api-new"
  # agent_endpoint = "chat-new"

  # Defining custom API endpoints
  gateway_endpoints = [
    {
      path           = "app"
      method         = "GET"
      overwrite_path = "/app"
    },
    {
      path           = "app_info"
      method         = "POST"
      overwrite_path = "/app_info"
    }
  ]

  # Queue mode (the module's default): this service is the edge, and Pub/Sub pushes each request
  # to a second, private agent-runner service built from the same image.
  agent_runner = {
    command = ["python", "-c", "from app import runner; runner()"]
  }

  # Environment variables passed to Cloud Run
  environment_variables = {
    "OPENAI_API_KEY" = var.openai_api_key
  }
}
