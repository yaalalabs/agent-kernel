# Containerized module configuration for deploying OpenAI Agent in ECS
# This is a documentation assistant that uses RAG to answer questions about Agent Kernel
# Endpoints exposed via API Gateway:
# /api/v1/chat - Documentation assistant chat endpoint
# /api/v1/version - Application version endpoint
# /api/v1/info - Custom endpoint created by custom handler
module "containered_agents" {
  source = "../../ak-deployment/ak-aws/containerized"

  # Basic ECS configuration
  product_alias        = var.product_alias
  env_alias            = var.env_alias
  module_name          = var.module_name
  package_path         = "../dist"
  container_type       = "ecs"
  region               = var.region
  vpc_id               = "vpc-09033229d67314c1c"
  private_subnet_ids   = ["subnet-00e888e445f16d1b1", "subnet-0ab5240262cd77119"]
  product_display_name = "AK Assistant"
  ecs_container_port   = 8000

  enable_cors        = true
  cors_allow_origins = ["http://localhost:3000", "https://kernel.yaala.ai"]
  cors_allow_methods = ["POST", "OPTIONS"]
  cors_allow_headers = ["content-type"]

  throttling_rate_limit  = "50"
  throttling_burst_limit = "50"
  # Environment variables passed to container
  environment_variables = {
    OPENAI_API_KEY = var.openai_api_key,
  }
}
