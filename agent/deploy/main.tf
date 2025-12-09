# Containerized module configuration for deploying OpenAI Agent in ECS
# This is a documentation assistant that uses RAG to answer questions about Agent Kernel
# Endpoints exposed via API Gateway:
# /api/v1/chat - Documentation assistant chat endpoint
# /api/v1/version - Application version endpoint
# /api/v1/info - Custom endpoint created by custom handler
module "containered_agents" {
  source = "yaalalabs/ak-containerized/aws"
  version = "0.2.7"

  # Basic ECS configuration
  product_alias        = var.product_alias
  env_alias            = var.env_alias
  module_name          = var.module_name
  package_path         = "../dist"
  container_type       = "ecs"
  region               = var.region
  vpc_id               = var.vpc_id
  private_subnet_ids   = var.private_subnet_ids
  product_display_name = "Agent Kernel OpenAI Containerized"
  ecs_container_port   = 8000
  
  gateway_endpoints = [
    {
      path           = "version",
      method         = "GET",
      overwrite_path = "/custom/version" # Application version endpoint
    },
    {
      path           = "info",
      method         = "GET",
      overwrite_path = "/whoami" # Custom handler endpoint
    }
  ]
  
  # Environment variables passed to container
  environment_variables = {
    OPENAI_API_KEY = var.openai_api_key,
    HOME           = "/tmp"
  }
}
