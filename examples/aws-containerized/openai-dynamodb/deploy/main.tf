# Containerized module configuration for deploying OpenAI Agent in ECS
module "containered_agents" {
  source  = "yaalalabs/ak-containerized/aws"
  version = "0.5.1"

  # Basic configuration
  product_alias        = var.product_alias
  env_alias            = var.env_alias
  module_name          = var.module_name
  region               = var.region
  product_display_name = "OpenAI Agents"

  vpc_id             = var.vpc_id
  private_subnet_ids = var.private_subnet_ids

  # REST Service configuration
  rest_service = {
    package_path          = "../dist"
    cpu                   = 256
    memory                = 512
    desired_count         = 1
    container_port        = 8000
    health_check_endpoint = "/health"
    environment_variables = {
      OPENAI_API_KEY = var.openai_api_key
    }
  }

  # Agent memory (session store)
  create_dynamodb_memory_table = true

  tags = {
    Example = "openai-dynamodb"
  }
}
