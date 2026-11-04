# Containered module configuration for deploying MCP in ECS
module "containered_agents" {
  source  = "yaalalabs/ak-containerized/aws"
  version = "0.9.5"

  providers = { aws = aws, docker = docker }
  # Basic ECS configuration
  prefix               = var.prefix
  container_type       = "ecs"
  region               = var.region
  vpc_id               = var.vpc_id
  private_subnet_ids   = var.private_subnet_ids
  product_display_name = "MCP Containered Example"
  create_redis_cluster = true
  enable_mcp_server    = true # endpoint = /<api_base_path>/<api_version>/mcp

  rest_service = {
    alb_security_group_id         = var.alb_security_group_id
    ecs_service_security_group_id = var.ecs_service_security_group_id
    package_path                  = "../dist"
    container_port                = 8000
    # Environment variables passed to container
    environment_variables = {
      OPENAI_API_KEY = var.openai_api_key
    }
  }
}
