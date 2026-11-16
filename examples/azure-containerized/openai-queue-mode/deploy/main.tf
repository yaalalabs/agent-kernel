module "containerd_agent" {
  source              = "yaalalabs/ak-containerized/azurerm"
  version             = "0.10.0"
  providers           = { azurerm = azurerm }
  prefix              = var.prefix
  resource_group_name = var.resource_group_name
  region              = var.region
  publisher_email     = var.publisher_email
  package_path        = "../dist"

  product_display_name        = "OpenAI Agents (queue mode)"
  container_port              = 8000
  container_health_check_path = "/health"

  # Edge + agent runner over Service Bus; Redis holds sessions and the replies the edge waits for.
  queue_mode              = true
  create_redis_cluster    = true
  create_cosmosdb_cluster = false

  is_production = false
  environment_variables = {
    OPENAI_API_KEY = var.openai_api_key
  }
  tags = {
    "costcenter" = "agent-kernel"
  }
}

data "azurerm_client_config" "current" {}

# Lets whoever runs the deploy (the CI service principal) create throwaway queues for
# servicebus_contract_test.py. Not needed to run the agents.
resource "azurerm_role_assignment" "deployer_servicebus_owner" {
  scope                = module.containerd_agent.servicebus_namespace_id
  role_definition_name = "Azure Service Bus Data Owner"
  principal_id         = data.azurerm_client_config.current.object_id
}
