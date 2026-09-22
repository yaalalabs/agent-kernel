module "FlexFunction" {
  source                  = "yaalalabs/ak-serverless/azurerm"
  version                 = "0.9.2"
  providers               = { azurerm = azurerm }
  prefix                  = var.prefix
  function_description    = "Agent Kernel OpenAI Sample Azure Function"
  function_name           = "openai-agents"
  module_type             = "python"
  region                  = var.region
  publisher_email         = var.publisher_email
  create_redis_cluster    = false
  create_cosmosdb_cluster = true
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
