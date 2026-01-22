region = "eastus"
# The Azure Resource Group you want to deploy the ACR into
resource_group_name = "rg-demo-dev"

# Product alias (used in ACR name and image name)
product_alias = "demo"

# Environment alias (dev, staging, prod, etc.)
env_alias = "dev"

# Module name (part of ACR and image name)
module_name = "api"

create_redis_cluster=true
create_cosmosdb_cluster=true

# Optional display name (used for tags, can be null)
product_display_name = "Demo Platform API"

# Whether this is a production environment
is_production = false

module_type = "nodejs"

package_path = "./Archive.zip"

environment_variables = {
  AK_IS_ADDED = "JustHere"
  AK_VTEST = "ItsHere"
}

function_name = "ak-api"
function_description = "AK API"
vnet_resource_group_name="rg-demo-dev"


tags = {
  "costcenter" = "nuwan"
}

cosmosdb_table_name="ak-memory"

sku_name_redis="Basic"
redis_node_family="C"


api_version = "v1"
apim_sku_name="Consumption_0"
gateway_endpoints = [
  {
    function_name = "HttpExample"
    path          = "/chat"
    method        = "POST"
  }
]
publisher_email="nuwan.udara@yaalalabs.com"