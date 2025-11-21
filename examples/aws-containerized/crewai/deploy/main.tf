# Containered module configuration for deploying CrewAI Agent in ECS
module "containered_agents" {
  source = "yaalalabs/ak-containerized/aws"
  version = "0.2.5"

  # Basic ECS configuration
  product_alias        = var.product_alias
  env_alias            = var.env_alias
  module_name          = var.module_name
  package_path         = "../dist"
  container_type       = "ecs"
  region               = var.region
  vpc_id               = "vpc-09033229d67314c1c"
  private_subnet_ids   = ["subnet-00e888e445f16d1b1", "subnet-0ab5240262cd77119"]
  product_display_name = "AK CrewAI Containered Example"
  ecs_container_port   = 8000

  # Environment variables passed to container
  environment_variables = {
    OPENAI_API_KEY     = var.openai_api_key,
    CREWAI_STORAGE_DIR = "/tmp/crewai",
    EMBEDCHAIN_DB_PATH = "/tmp/crewai/embedchain.db",
    HOME               = "/tmp"
  }
}
