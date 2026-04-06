# Cloud Run module configuration for deploying OpenAI Agent
# This example exposes the following endpoints via API Gateway
# /api/v1/chat - Agent execution
# /api/v1/app - Custom endpoint created via a direct route addition
# /api/v1/app_info - Custom endpoint created by a custom handler
module "containerized_agents" {
  source = "../../../../ak-deployment/ak-gcp/containerized"
  # source  = "yaalalabs/ak-containerized/google"  # uncomment for registry
  # version = "0.2.14"                             # uncomment for registry

  # Basic Cloud Run configuration
  project_id           = var.project_id
  product_alias        = var.product_alias
  env_alias            = var.env_alias
  module_name          = var.module_name
  package_path         = "../dist"
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
  # Environment variables passed to container
  environment_variables = {
    OPENAI_API_KEY = var.openai_api_key
  }
}
