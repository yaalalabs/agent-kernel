# ---------- DynamoDB Response Store ----------

resource "aws_dynamodb_table" "response_store" {
  count = var.enable_queue_mode ? 1 : 0

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
