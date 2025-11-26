module "dynamodb_table" {
  source = "terraform-aws-modules/dynamodb-table/aws"
  version = "5.3.0"

  # Naming
  name = "${var.product_alias}-${var.env_alias}-${var.module_name}-${var.table_name}"

  # Keys & attributes
  attributes = var.attributes
  hash_key   = var.hash_key
  range_key = var.range_key

  # Capacity & billing
  billing_mode  = var.billing_mode
  read_capacity = var.read_capacity
  write_capacity = var.write_capacity

  # Indexes
  global_secondary_indexes = var.global_secondary_indexes
  local_secondary_indexes = var.local_secondary_indexes

  # TTL
  ttl_enabled = var.ttl_enabled
  ttl_attribute_name = var.ttl_attribute_name

  # Streams
  stream_enabled = var.stream_enabled
  stream_view_type = var.stream_view_type

  # Data protection
  point_in_time_recovery_enabled     = var.point_in_time_recovery_enabled
  server_side_encryption_enabled     = var.server_side_encryption_enabled
  server_side_encryption_kms_key_arn = var.kms_key_arn
  deletion_protection_enabled        = var.deletion_protection_enabled

  tags = var.tags
}
