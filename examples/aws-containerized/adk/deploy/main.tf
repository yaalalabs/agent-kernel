# Containered module configuration for deploying Google ADK Agent in ECS
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
  product_display_name = "AK Google ADK Containered Example"

  # Secret resolution: grants ssm:GetParameter on /ak/<prefix>/* and injects AK_SECRET__PREFIX, so the app
  # resolves OPENAI_API_KEY from /ak/<prefix>/<key lowercased> (config.yaml `secret:` block)
  # Terraform creates each parameter holding REPLACE_ME; overwrite it with the real value after the first apply.
  ssm_enabled     = true
  ssm_secret_keys = ["OPENAI_API_KEY"]

  rest_service = {
    alb_security_group_id         = var.alb_security_group_id
    ecs_service_security_group_id = var.ecs_service_security_group_id
    package_path                  = "../dist"
    container_port                = 8000
    # Environment variables passed to container
  }
}
