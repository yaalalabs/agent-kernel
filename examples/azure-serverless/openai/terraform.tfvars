# Azure region, try to use the same as your resource group to avoid cross-region issues and costs. Make sure the resources are available in the region you specify.
region = "centralus"
# The Azure Resource Group you want to deploy the resources into
resource_group_name = ""

# Product alias
product_alias = "demo"

# Environment alias (dev, staging, d, etc.)
env_alias = "dev"

# Module name
module_name = "api"

# Choose whether to create a Redis cluster or not
create_redis_cluster=false
# Choose whether to create a CosmosDB or not
create_cosmosdb_cluster=true

# Optional display name (used for tags, can be null)
product_display_name = "Demo Platform API"

# Whether this is a production environment
is_production = false

module_type = "python"

package_path = "./dist.zip"

function_name = "ak-api"
function_description = "AK API"
vnet_resource_group_name="rg-demo-dev"


tags = {
  "costcenter" = ""
}

cosmosdb_table_name="ak-memory"


api_version = "v1"
apim_sku_name="Consumption_0"
gateway_endpoints = [
  {
    function_name = "AgentFunction"
    path          = "/chat"
    method        = "POST"
  }
]
publisher_email="agentkernel@yaala.ai"
#

openai_api_key=""