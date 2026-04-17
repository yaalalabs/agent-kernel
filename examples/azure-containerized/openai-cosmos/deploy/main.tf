module "containerd_agent" {
  source              = "yaalalabs/ak-containerized/azurerm"
  version             = "0.3.2"
  product_alias       = var.product_alias
  env_alias           = var.env_alias
  module_name         = var.module_name
  resource_group_name = var.resource_group_name
  region              = var.region
  publisher_email     = var.publisher_email
  package_path        = "../dist"

  product_display_name        = "OpenAI Agents"
  container_port              = 8000
  container_health_check_path = "/health"

  api_version             = "0.3.2"
  is_production           = false
  create_redis_cluster    = true
  create_cosmosdb_cluster = false
  environment_variables = {
    OPENAI_API_KEY = var.openai_api_key
  }
  tags = {
    "costcenter" = "agent-kernel"
  }

  gateway_endpoints = [
    {
      path           = "chat"
      method         = "POST"
      overwrite_path = "/run"
    }
  ]

}
