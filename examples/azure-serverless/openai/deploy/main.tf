module "FlexFunction" {
  source                  = "yaalalabs/ak-serverless/azurerm"
  version                 = "0.5.0"
  product_alias           = var.product_alias
  env_alias               = var.env_alias
  function_description    = "Agent Kernel OpenAI Sample Azure Function"
  function_name           = "openai-agents"
  module_name             = var.module_name
  module_type             = "python"
  region                  = var.region
  publisher_email         = var.publisher_email
  create_redis_cluster    = true
  create_cosmosdb_cluster = false
  resource_group_name     = var.resource_group_name
  package_path            = "../dist.zip"
  is_production           = false
  environment_variables = {
    "OPENAI_API_KEY" = var.openai_api_key
  }

  gateway_endpoints = [
    {
      function_name = "AgentFunction"
      path          = "/chat"
      method        = "POST"
      }, {
      function_name = "CustomFunction"
      path          = "/custom"
      method        = "POST"
    }

  ]
}
