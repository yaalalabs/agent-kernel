# Azure region, try to use the same as your resource group to avoid cross-region issues and costs. Make sure the resources are available in the region you specify.
region = "centralus"
# The Azure Resource Group you want to deploy the resources into
resource_group_name = ""

product_alias = "demo"

env_alias = "dev"

module_name = "api"

create_redis_cluster=true
create_cosmosdb_cluster=false


# Whether this is a production environment
is_production = false

module_type = "python"


gateway_endpoints = [
  {
    function_name = "AgentFunction"
    path          = "/chat"
    method        = "POST"
  },{
    function_name = "AgentFunction"
    path          = "/secondary"
    method        = "POST"
  }

]
# Email integration for Azure APIM
publisher_email="agentkernel@yaala.ai"

# OpenAI API key
openai_api_key=""