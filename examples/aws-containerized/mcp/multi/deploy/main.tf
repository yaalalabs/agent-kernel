# Containerized module configuration for deploying MCP in ECS
module "containered_agents" {
  source  = "yaalalabs/ak-containerized/aws"
  version = "0.5.1"

  # Basic configuration
  product_alias        = var.product_alias
  env_alias            = var.env_alias
  module_name          = var.module_name
  region               = var.region
  product_display_name = "MCP Containerized Example"

  vpc_id             = var.vpc_id
  private_subnet_ids = var.private_subnet_ids

  # Docker image path
  package_path = "../dist"

  # REST Service configuration
  rest_service = {
    cpu                   = 256
    memory                = 512
    desired_count         = 1
    container_port        = 8000
    health_check_endpoint = "/health"
    environment_variables = {
      OPENAI_API_KEY = var.openai_api_key
    }
  }

  # Session storage
  create_redis_cluster = true

  # Enable MCP server endpoint: /<api_base_path>/<api_version>/mcp
  enable_mcp_server = true

  tags = {
    Example = "mcp-multi"
  }
}
