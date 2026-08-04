# Containered module configuration for deploying OpenAI Agent in ECS
module "containered_agents" {
  source = "yaalalabs/ak-containerized/aws"
  version = "0.8.0"

  # Basic ECS configuration
  product_alias                = var.product_alias
  env_alias                    = var.env_alias
  module_name                  = var.module_name
  container_type               = "ecs"
  region                       = var.region
  vpc_id                       = var.vpc_id
  create_dynamodb_memory_table = true
  private_subnet_ids           = var.private_subnet_ids
  product_display_name         = "OpenAI Agents"

  rest_service = {
    package_path   = "../dist"
    container_port = 8000
    image_uri      = var.ecr_image_uri
    # Environment variables passed to container
    environment_variables = {
      OPENAI_API_KEY = var.openai_api_key
    }
  }
}