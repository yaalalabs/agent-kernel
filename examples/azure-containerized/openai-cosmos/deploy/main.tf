module "containerd_agent" {
  source                      = "../../../../ak-deployment/ak-azure/containerized"
  product_alias               = var.product_alias
  env_alias                   = var.env_alias
  module_name                 = var.module_name
  package_path                = "../dist"
  region                      = var.region
  product_display_name        = "OpenAI Agents"
  container_port              = var.container_port
  container_health_check_path = var.container_health_check_path
  tags                        = var.tags
  api_version                 = var.api_version
  gateway_endpoints           = var.gateway_endpoints
  environment_variables       = var.environment_variables
  is_production               = var.is_production
  create_redis_cluster        = var.create_redis_cluster
  create_cosmosdb_cluster     = var.create_cosmosdb_cluster
  resource_group_name         = var.resource_group_name
  publisher_email             = var.publisher_email
}
