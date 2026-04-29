# DynamoDB Table for WebSocket Connection Mapping
module "websocket_connections" {
  source = "../../../common/modules/dynamodb"

  product_alias = var.product_alias
  env_alias     = var.env_alias
  module_name   = "websocket-api"
  table_name    = "connections"
  tags          = var.tags

  # Keys & attributes
  attributes = [
    { name = "user_id", type = "S" },
    { name = "connection_id", type = "S" }
  ]
  hash_key  = "user_id"
  range_key = "connection_id"

  # Capacity & billing
  billing_mode  = var.dynamodb_billing_mode
  read_capacity = var.dynamodb_read_capacity
  write_capacity = var.dynamodb_write_capacity

  # Global Secondary Index for connection_id lookups
  global_secondary_indexes = [
    {
      name            = "connection_id-index"
      hash_key        = "connection_id"
      projection_type = "ALL"
      read_capacity    = var.dynamodb_billing_mode == "PROVISIONED" ? var.dynamodb_read_capacity : null
      write_capacity   = var.dynamodb_billing_mode == "PROVISIONED" ? var.dynamodb_write_capacity : null
    }
  ]

  # TTL for automatic cleanup of stale connections
  ttl_enabled        = var.enable_ttl
  ttl_attribute_name = "expires_at"

  # Data protection
  point_in_time_recovery_enabled = var.enable_point_in_time_recovery
  server_side_encryption_enabled = var.enable_encryption
  kms_key_arn                    = var.encryption_kms_key_arn
  deletion_protection_enabled    = var.deletion_protection_enabled
}
