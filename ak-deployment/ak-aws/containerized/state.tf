data "aws_vpc" "provided" {
  count = var.vpc_id != null ? 1 : 0
  id    = var.vpc_id
}

locals {
  vpc_id                    = var.vpc_id != null ? var.vpc_id : module.vpc[0].vpc_id
  vpc_cidr                  = var.vpc_id != null ? data.aws_vpc.provided[0].cidr_block : var.vpc_cidr
  subnet_ids                = var.vpc_id != null ? var.private_subnet_ids : module.vpc[0].private_subnet_ids
  redis_url                 = var.create_redis_cluster == true ? module.redis[0].url : null
  dynamodb_memory_table_arn = var.create_dynamodb_memory_table == true ? module.dynamodb_memory[0].table_arn : null
  dynamodb_memory_table_name = var.create_dynamodb_memory_table == true ? module.dynamodb_memory[0].table_name : null
  prefix                    = "${var.product_alias}-${var.env_alias}-${var.module_name}"
  service_name              = "${local.prefix}-service"
  container_name            = "${local.prefix}-app"

  api_base_segment = try(trim(var.api_base_path, "/"), "")
  api_base_segment_with_version = "/${join("/", compact([local.api_base_segment, var.api_version]))}"
  default_endpoint_path = "${join("/", compact([local.api_base_segment_with_version, var.agent_endpoint]))}"
  default_gateway_endpoint = {
    path           = local.default_endpoint_path
    method         = "POST"
    overwrite_path = "/api/v1/chat"
  }
  multipart_endpoint_path = "${join("/", compact([local.api_base_segment_with_version, "${var.agent_endpoint}-multipart"]))}"
  multipart_gateway_endpoint = {
    path           = local.multipart_endpoint_path
    method         = "POST"
    overwrite_path = "/api/v1/chat-multipart"
  }
  default_gateway_map = {
    "${upper(local.default_gateway_endpoint.method)} ${local.default_gateway_endpoint.path}" = local.default_gateway_endpoint
    "${upper(local.multipart_gateway_endpoint.method)} ${local.multipart_gateway_endpoint.path}" = local.multipart_gateway_endpoint
  }
  user_gateway_map = {
    for ep in var.gateway_endpoints :
    (
      lower(try(ep["method"], "")) == "$default"
      ? "$default"
      : "${upper(try(ep["method"], "ANY"))} ${join("/", compact([local.api_base_segment_with_version, trim(try(ep["path"], ""), "/")]))}"
    ) => ep
  }
  mcp_endpoint_path = "${join("/", compact([local.api_base_segment_with_version, "mcp"]))}"
  mcp_gateway_map = var.enable_mcp_server ? {
    "ANY ${local.mcp_endpoint_path}" = {
      path           = "mcp"
      method         = "ANY"
      overwrite_path = "/mcp/"
    }
  } : {}
  gateway_endpoints_map = merge(local.default_gateway_map, local.mcp_gateway_map, local.user_gateway_map)
}

module "vpc" {
  source               = "yaalalabs/ak-common/aws//modules/vpc"
  version              = "0.5.0"
  count                = var.vpc_id == null ? 1 : 0
  vpc_cidr             = var.vpc_cidr
  public_subnet_cidrs  = var.public_subnet_cidrs
  private_subnet_cidrs = var.private_subnet_cidrs
  product_alias        = var.product_alias
  env_alias            = var.env_alias
  tags                 = var.tags
}

module "redis" {
  source        = "yaalalabs/ak-common/aws//modules/redis"
  version       = "0.5.0"
  count         = var.create_redis_cluster == true ? 1 : 0
  env_alias     = var.env_alias
  module_name   = var.module_name
  product_alias = var.product_alias
  vpc_cidr      = local.vpc_cidr
  vpc_id        = local.vpc_id
  subnet_ids    = local.subnet_ids
}

module "docker_image" {
  count         = 1
  source        = "yaalalabs/ak-common/aws//modules/ecr"
  version       = "0.5.0"
  env_alias     = var.env_alias
  module_name   = var.module_name
  product_alias = var.product_alias
  source_path   = var.package_path
}

module dynamodb_memory {
  source  = "yaalalabs/ak-common/aws//modules/dynamodb"
  version = "0.5.0"
  count   = var.create_dynamodb_memory_table == true ? 1 : 0
  attributes = [
    { name = "session_id", type = "S" },
    { name = "key", type = "S" },
  ]
  hash_key           = "session_id"
  range_key          = "key"
  ttl_enabled        = true
  env_alias          = var.env_alias
  module_name        = var.module_name
  product_alias      = var.product_alias
  table_name         = "session_store"
  ttl_attribute_name = "expiry_time"
}