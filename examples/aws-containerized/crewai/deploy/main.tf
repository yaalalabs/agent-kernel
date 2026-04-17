# Containerized module configuration for deploying CrewAI Agent in ECS
# This example exposes the following endpoints via API Gateway
# /api/v1/chat - Agent execution
# /api/v1/app - Custom endpoint created via a direct route addition
# /api/v1/app_info - Custom endpoint created by a custom handler
module "containered_agents" {
  source = "yaalalabs/ak-containerized/aws"
  version = "0.3.2"

  # Basic ECS configuration
  product_alias        = var.product_alias
  env_alias            = var.env_alias
  module_name          = var.module_name
  package_path         = "../dist"
  container_type       = "ecs"
  region               = var.region
  vpc_id               = "vpc-09033229d67314c1c"
  private_subnet_ids   = ["subnet-00e888e445f16d1b1", "subnet-0ab5240262cd77119"]
  product_display_name = "AK CrewAI Containerized Example"
  ecs_container_port   = 8000
  gateway_endpoints = [
    {
      path           = "app",
      method         = "GET",
      overwrite_path = "/custom/version" # The default `/custom` prefix should be added for routes added via direct custom route capability
    },
    {
      path           = "app_info",
      method         = "GET",
      overwrite_path = "/whoami"
    }
  ]
  # Environment variables passed to container
  environment_variables = {
    OPENAI_API_KEY     = var.openai_api_key,
    CREWAI_STORAGE_DIR = "/tmp/crewai",
    EMBEDCHAIN_DB_PATH = "/tmp/crewai/embedchain.db",
    HOME               = "/tmp"
  }
}
