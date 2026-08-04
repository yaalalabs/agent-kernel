# Containered module configuration for deploying MCP in ECS
module "containered_agents" {
  source = "yaalalabs/ak-containerized/aws"
  version = "0.8.0"

  # Basic ECS configuration
  product_alias        = var.product_alias
  env_alias            = var.env_alias
  module_name          = var.module_name
  container_type       = "ecs"
  region               = var.region
  vpc_id               = var.vpc_id
  private_subnet_ids   = var.private_subnet_ids
  product_display_name = "MCP Containered Example"
  create_redis_cluster = true
  enable_mcp_server    = true # endpoint = /<api_base_path>/<api_version>/mcp

  rest_service = {
    package_path   = "../dist"
    container_port = 8000
    # Environment variables passed to container
    environment_variables = {
      OPENAI_API_KEY = var.openai_api_key
    }
  }
}
