module "FlexFunction" {
  source                  = "../../../../ak-deployment/ak-azure/serverless"
  product_alias           = var.product_alias
  env_alias               = var.env_alias
  function_description    = "Agent Kernel OpenAI Sample Lambda"
  function_name           = "openai-agents"
  module_name             = var.module_name
  module_type             = var.module_type
  region                  = var.region
  publisher_email         = var.publisher_email
  gateway_endpoints       = var.gateway_endpoints
  create_redis_cluster    = var.create_redis_cluster
  create_cosmosdb_cluster = var.create_cosmosdb_cluster
  resource_group_name     = var.resource_group_name
  package_path            = "../dist.zip"
  environment_variables = {
    "OPENAI_API_KEY" = var.openai_api_key
  }
}
