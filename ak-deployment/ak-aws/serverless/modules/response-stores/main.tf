# Redis cluster for response storage
module "redis_response_store" {
  source  = "yaalalabs/ak-common/aws//modules/redis"
  version = "0.2.14"
  count   = var.create_redis ? 1 : 0
  
  env_alias     = var.env_alias
  module_name   = "${var.module_name}-${coalesce(var.response_store_suffix, "response-store")}"
  product_alias = var.product_alias
  vpc_cidr      = var.vpc_cidr
  vpc_id        = var.vpc_id
  subnet_ids    = var.subnet_ids
}

# DynamoDB table for response storage
module "dynamodb_response_store" {
  source  = "yaalalabs/ak-common/aws//modules/dynamodb"
  version = "0.2.14"
  count   = var.create_dynamodb ? 1 : 0
  
  attributes = [
    { name = "session_id", type = "S" },
    { name = "message_id", type = "S" },
  ]
  hash_key           = "session_id"
  range_key          = "message_id"
  ttl_enabled        = true
  env_alias          = var.env_alias
  module_name        = "${var.module_name}-${coalesce(var.response_store_suffix, "response-store")}"
  product_alias      = var.product_alias
  table_name         = var.dynamodb_table_name
  ttl_attribute_name = "expiry_time"
}