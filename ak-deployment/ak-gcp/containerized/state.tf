# Resolve network — use provided or create new

resource "random_id" "deployment" {
  byte_length = 4
}

resource "random_id" "connector" {
  byte_length = 2
}

locals {
  network_id        = var.network_id != null ? var.network_id : module.vpc[0].network_id
  network_name      = var.network_id != null ? null : module.vpc[0].network_name
  private_subnet_id = var.network_id != null ? var.private_subnet_id : module.vpc[0].private_subnet_id
  redis_url         = var.create_redis_cluster ? module.redis[0].full_redis_url : null
  firestore_db_name = var.create_firestore_database ? module.firestore[0].database_name : null

  # Unique deployment identifier (8 hex chars)
  deployment_id = random_id.deployment.hex

  # Compute unique connector CIDR to avoid conflicts across deployments
  # Use last byte of deployment_id hash to generate unique /28 subnet in 10.9.0.0/16 range
  # This gives us 256 possible /28 subnets (10.9.0.0/28, 10.9.0.16/28, ..., 10.9.255.240/28)
  connector_cidr_computed = var.connector_cidr != null ? var.connector_cidr : "10.9.${floor(random_id.deployment.dec / 16777216) % 256}.${(floor(random_id.deployment.dec / 65536) % 16) * 16}/28"

  # Naming prefix — used everywhere
  prefix       = "${var.product_alias}-${var.env_alias}-${var.module_name}"
  service_name = "${local.prefix}-svc" #service name cannot exceed 49

  # GCP service account IDs must be 6-30 chars.
  # Truncate the prefix to 27 chars max, then append "-run" (= 31... use 26 + "-run" = 30).
  sa_prefix = "${var.product_alias}-${var.env_alias}-${var.module_name}"
  sa_id     = "${substr(local.sa_prefix, 0, min(length(local.sa_prefix), 26))}-run"

  # VPC Access Connector name must match ^[a-z][-a-z0-9]{0,23}[a-z0-9]$ (max 25 chars).
  # Must start with letter, end with alphanumeric, contain only lowercase letters, numbers, hyphens
  # Strategy: use first letter of product_alias + deployment_id + letter suffix
  # Format: a<7hex>-<8hex>-c = 1+7+1+8+1+1 = 19 chars (safe)
  connector_name = "a${substr(local.deployment_id, 0, 7)}-${local.deployment_id}-c"

  # Firewall name with unique deployment ID
  firewall_name = "${substr(local.prefix, 0, min(length(local.prefix), 45))}-${local.deployment_id}-fw"

  # API Gateway names with unique deployment ID (max 49 chars for gateway, 63 for API)
  # Gateway regex: ^[a-z0-9]([a-z0-9-]{0,47}[a-z0-9])?$ = max 49 chars
  # Reserve 13 chars for suffix: -<8hex>-gw = 13 chars, leaving 36 for prefix
  api_id      = "${substr(local.prefix, 0, min(length(local.prefix), 50))}-${local.deployment_id}-api"
  gateway_id  = "${substr(local.prefix, 0, min(length(local.prefix), 36))}-${local.deployment_id}-gw"

  # Build the endpoint map for API Gateway
  # Same pattern as AWS: default + multipart + MCP + user endpoints
  api_base_segment              = trim(var.api_base_path, "/")
  api_base_segment_with_version = "/${join("/", compact([local.api_base_segment, var.api_version]))}"

  default_endpoint_path = join("/", compact([local.api_base_segment_with_version, var.agent_endpoint]))
  default_gateway_endpoint = {
    path           = local.default_endpoint_path
    method         = "POST"
    overwrite_path = "/api/v1/chat"
  }

  multipart_endpoint_path = join("/", compact([local.api_base_segment_with_version, "${var.agent_endpoint}-multipart"]))
  multipart_gateway_endpoint = {
    path           = local.multipart_endpoint_path
    method         = "POST"
    overwrite_path = "/api/v1/chat-multipart"
  }

  # Default endpoints map
  default_gateway_map = {
    "${upper(local.default_gateway_endpoint.method)} ${local.default_gateway_endpoint.path}"     = local.default_gateway_endpoint
    "${upper(local.multipart_gateway_endpoint.method)} ${local.multipart_gateway_endpoint.path}" = local.multipart_gateway_endpoint
  }

  # User-provided endpoints
  user_gateway_map = {
    for ep in var.gateway_endpoints :
    "${upper(ep.method)} ${join("/", compact([local.api_base_segment_with_version, trim(ep.path, "/")]))}" => {
      path           = join("/", compact([local.api_base_segment_with_version, trim(ep.path, "/")]))
      method         = ep.method
      overwrite_path = ep.overwrite_path
    }
  }

  # MCP endpoint (if enabled)
  mcp_endpoint_path = join("/", compact([local.api_base_segment_with_version, "mcp"]))
  mcp_gateway_map = var.enable_mcp_server ? {
    "ANY ${local.mcp_endpoint_path}" = {
      path           = local.mcp_endpoint_path
      method         = "ANY"
      overwrite_path = "/mcp/"
    }
  } : {}

  # Merge all endpoints — user endpoints override defaults
  gateway_endpoints_map = merge(local.default_gateway_map, local.mcp_gateway_map, local.user_gateway_map)

  # Authorizer
  create_authorizer = var.authorizer != null
  authorizer_status_message = local.create_authorizer ? (
    "JWT Authorizer configured (issuer: ${var.authorizer.issuer})"
  ) : "No authorizer configured — endpoints are publicly accessible"
}

# VPC — only create if no network_id provided
module "vpc" {
  source = "yaalalabs/ak-common/google//modules/vpc"
  count = var.network_id == null ? 1 : 0

  project_id          = var.project_id
  region              = var.region
  product_alias       = var.product_alias
  env_alias           = var.env_alias
  public_subnet_cidr  = var.public_subnet_cidr
  private_subnet_cidr = var.private_subnet_cidr
}

# Docker image — build and push to Artifact Registry
module "docker_image" {
  source = "yaalalabs/ak-common/google//modules/artifact-registry"


  project_id    = var.project_id
  region        = var.region
  product_alias = var.product_alias
  env_alias     = var.env_alias
  module_name   = var.module_name
  source_path   = var.package_path
}

# Redis — optional session cache
module "redis" {
  source = "yaalalabs/ak-common/google//modules/memorystore"  # uncomment for registry
  count = var.create_redis_cluster ? 1 : 0

  project_id    = var.project_id
  region        = var.region
  product_alias = var.product_alias
  env_alias     = var.env_alias
  module_name   = var.module_name
  network_id    = local.network_id
}

# Firestore — optional session storage
module "firestore" {
  source = "yaalalabs/ak-common/google//modules/firestore"  # uncomment for registry
  count = var.create_firestore_database ? 1 : 0

  project_id    = var.project_id
  region        = var.region
  product_alias = var.product_alias
  env_alias     = var.env_alias
  module_name   = var.module_name
}
