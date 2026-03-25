# DynamoDB Table for WebSocket Connections
resource "aws_dynamodb_table" "websocket_connections" {
  name           = "${var.product_alias}-${var.env_alias}-${var.table_name}"
  billing_mode   = var.billing_mode
  hash_key       = var.hash_key
  range_key      = var.range_key

  attribute {
    name = var.hash_key
    type = "S"
  }

  attribute {
    name = var.range_key
    type = "S"
  }

  # Global Secondary Index for faster connection_id lookups
  global_secondary_index {
    name               = var.gsi_name
    projection_type    = var.gsi_projection_type

    key_schema {
      attribute_name = var.gsi_hash_key
      key_type       = "HASH"
    }
  }

  # TTL for automatic cleanup of stale connections
  ttl {
    attribute_name = var.ttl_attribute_name
    enabled        = var.ttl_enabled
  }

  tags = merge(var.tags, {
    Name = "${var.product_alias}-${var.env_alias}-${var.table_name}"
  })
}