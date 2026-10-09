# Containerized module configuration for deploying OpenAI Agent in ECS
# This is a documentation assistant that uses RAG to answer questions about Agent Kernel
# Endpoints exposed via API Gateway:
# /api/v1/chat - Documentation assistant chat endpoint
# /api/v1/version - Application version endpoint
# /api/v1/info - Custom endpoint created by custom handler
#
# Networking is reused from the weekly integration base deployment (examples/aws-serverless/openai):
# its VPC and private subnets (and so its NAT gateway), instead of provisioning a dedicated VPC + NAT
# here. Set vpc_id/private_subnet_ids to override.
data "terraform_remote_state" "base" {
  backend = "s3"
  config = {
    bucket = "agent-kernel-terraform-state-bucket-dev"
    key    = "examples/aws-serverless/openai/terraform.tfstate"
    region = "ap-southeast-2"
  }
}

locals {
  vpc_id             = coalesce(var.vpc_id, data.terraform_remote_state.base.outputs.vpc_id)
  private_subnet_ids = var.private_subnet_ids != null ? var.private_subnet_ids : data.terraform_remote_state.base.outputs.private_subnet_ids
}

module "containered_agents" {
  source = "../../ak-deployment/ak-aws/containerized"

  providers = { aws = aws, docker = docker }
  # Basic ECS configuration
  prefix               = var.prefix
  container_type       = "ecs"
  region               = var.region
  vpc_id               = local.vpc_id
  private_subnet_ids   = local.private_subnet_ids
  product_display_name = "AK Assistant"
  enable_cors          = true
  cors_allow_origins   = ["http://localhost:3000", "https://kernel.yaala.ai"]
  cors_allow_methods   = ["POST", "OPTIONS"]
  cors_allow_headers   = ["content-type"]

  throttling_rate_limit  = 50
  throttling_burst_limit = 50

  rest_service = {
    package_path   = "../dist"
    container_port = 8000
    # Environment variables passed to container
    environment_variables = {
      OPENAI_API_KEY      = var.openai_api_key,
      LANGFUSE_SECRET_KEY = var.langfuse_secret_key,
      LANGFUSE_PUBLIC_KEY = var.langfuse_public_key,
      LANGFUSE_BASE_URL   = var.langfuse_base_url
    }
  }
}
