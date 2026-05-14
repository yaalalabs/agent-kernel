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
  version = "0.2.14"

  # Basic Cloud Run configuration
  project_id           = var.project_id
  product_alias        = var.product_alias
  env_alias            = var.env_alias
  module_name          = var.module_name
  package_path         = "../dist"
  memory               = "512Mi"
  create_redis_cluster = true
  product_display_name = "AK OpenAI Serverless Example"
  region               = var.region
  container_port       = 8080

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

  # Environment variables passed to Cloud Run
  environment_variables = {
    "OPENAI_API_KEY" = var.openai_api_key
  }
}
