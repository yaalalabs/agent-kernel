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


# Whether this is a production environment
is_production = false

module_type = "python"


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