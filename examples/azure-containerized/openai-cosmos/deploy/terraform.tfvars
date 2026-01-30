region = "centralus"
# The Azure Resource Group you want to deploy the ACR into
resource_group_name = "central_resources"

# Product alias (used in ACR name and image name)
product_alias = "ak-oai"

# Environment alias (dev, staging, d, etc.)
env_alias = "dev"

# Module name (part of ACR and image name)
module_name = "examples"

create_redis_cluster=false
create_cosmosdb_cluster=true

# Optional display name (used for tags, can be null)
product_display_name = "Demo Platform API"

# Whether this is a production environment
is_production = false


package_path = "dist"

environment_variables = {
  OPENAI_API_KEY = ""
}


container_port              = 8000
container_health_check_path = "/health"

tags = {
  "costcenter" = "agent-kernel"
}



api_version = "v1"

gateway_endpoints = [
  {
    path           = "chat"           # API path will be /api/v1/chat
    method         = "POST"
    overwrite_path = "/run"           # Forwards to container's /run endpoint
  }
]


publisher_email="" 
