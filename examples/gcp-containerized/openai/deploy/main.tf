# Cloud Run module configuration for deploying OpenAI Agent
# This example exposes the following endpoints via API Gateway
# /api/v1/chat - Agent execution
# /api/v1/app - Custom endpoint created via a direct route addition
# /api/v1/app_info - Custom endpoint created by a custom handler
module "containerized_agents" {
  source  = "yaalalabs/ak-containerized/google"
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
  region               = var.region
  product_display_name = "AK OpenAI Containerized Example"
  container_port       = 8000
  create_redis_cluster = true
  gateway_endpoints = [
    {
      path           = "app",
      method         = "GET",
      overwrite_path = "/custom/version"
    },
    {
      path           = "app_info",
      method         = "GET",
      overwrite_path = "/whoami"
    }
  ]

  # Queue mode (the module's default): this service is the edge, and Pub/Sub pushes each request
  # to a second, private agent-runner service built from the same image.
  agent_runner = {
    command = ["python", "-c", "from app import runner; runner()"]
  }

  # Environment variables passed to container
  environment_variables = {
    OPENAI_API_KEY = var.openai_api_key
  }
}
