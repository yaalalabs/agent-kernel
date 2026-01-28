region = "centralus"
# The Azure Resource Group you want to deploy the ACR into
resource_group_name = ""

# Product alias (used in ACR name and image name)
product_alias = "demo"

# Environment alias (dev, staging, d, etc.)
env_alias = "dev"

# Module name (part of ACR and image name)
module_name = "api"

create_redis_cluster=true
create_cosmosdb_cluster=false

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