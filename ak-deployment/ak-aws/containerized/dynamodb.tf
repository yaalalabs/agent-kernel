# ---------- DynamoDB Response Store ----------
# Not used in WebSocket modes (responses are pushed over the connection).

resource "aws_dynamodb_table" "response_store" {
  count = var.queue_mode && !local.is_websocket_mode ? 1 : 0

  name         = "${local.prefix}-response-store"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "request_id"

  attribute {
    name = "request_id"
    type = "S"
  }

  ttl {
    attribute_name = "expiry_time"
    enabled        = true
  }

  tags = merge(var.tags, { Type = "ResponseStore" })
}

# WebSocket connections table, maps user_id <-> connection_id (WebSocket modes only)

module "websocket_connections" {
  source  = "yaalalabs/ak-common/aws//modules/dynamodb"
  version = "0.6.1"
  count   = local.is_websocket_mode ? 1 : 0

  attributes = [
    { name = "user_id", type = "S" },
    { name = "connection_id", type = "S" },
  ]
  hash_key  = "user_id"
  range_key = "connection_id"
  global_secondary_indexes = [
    {
      name            = "connection_id-index"
      hash_key        = "connection_id"
      range_key       = "user_id"
      projection_type = "ALL"
    },
  ]
  ttl_enabled        = true
  ttl_attribute_name = "expiry_time"
  env_alias          = var.env_alias
  module_name        = var.module_name
  product_alias      = var.product_alias
  table_name         = "websocket-connections"
  tags               = merge(var.tags, { Type = "WebSocketConnections" })
}
