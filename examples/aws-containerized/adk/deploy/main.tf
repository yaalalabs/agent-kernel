# Containered module configuration for deploying Google ADK Agent in ECS
module "containered_agents" {
  source = "yaalalabs/ak-containerized/aws"
  version = "0.3.3"

  # Basic ECS configuration
  product_alias        = var.product_alias
  env_alias            = var.env_alias
  module_name          = var.module_name
  package_path         = "../dist"
  container_type       = "ecs"
  region               = var.region
  vpc_id               = var.vpc_id
  private_subnet_ids   = var.private_subnet_ids
  product_display_name = "AK Google ADK Containered Example"
  ecs_container_port   = 8000

  # Environment variables passed to container
  environment_variables = {
    OPENAI_API_KEY = var.openai_api_key
  }
}
