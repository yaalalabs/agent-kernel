data "aws_region" "current" {}

# ---------- SQS Input Queue ----------

module "input_queue" {
  source  = "yaalalabs/ak-common/aws//modules/sqs"
  version = "0.5.1"

  product_alias        = var.product_alias
  env_alias            = var.env_alias
  module_name          = var.module_name
  queue_name           = var.queue_config.input_queue_name
  region               = data.aws_region.current.name
  product_display_name = var.product_alias
  is_production        = var.env_alias == "prod"

  fifo_queue                  = true
  content_based_deduplication = false
  deduplication_scope         = "messageGroup"
  fifo_throughput_limit       = "perMessageGroupId"

  visibility_timeout_seconds    = var.queue_config.input_queue_visibility_timeout
  message_retention_seconds     = var.queue_config.input_queue_message_retention_seconds
  max_message_size              = var.queue_config.max_message_size
  receive_wait_time_seconds     = var.queue_config.receive_wait_time_seconds
  max_receive_count             = var.queue_config.input_queue_max_receive_count
  create_dlq                    = var.queue_config.input_queue_create_dlq
  dlq_message_retention_seconds = var.queue_config.input_queue_dlq_message_retention_seconds

  sqs_managed_sse_enabled = var.queue_config.sqs_managed_sse_enabled

  # IAM access is managed via ECS task role policies
  enable_producer_access = false
  enable_consumer_access = false

  tags = merge(var.tags, { Type = "InputQueue" })
}

# ---------- SQS Output Queue ----------

module "output_queue" {
  source  = "yaalalabs/ak-common/aws//modules/sqs"
  version = "0.5.1"

  product_alias        = var.product_alias
  env_alias            = var.env_alias
  module_name          = var.module_name
  queue_name           = var.queue_config.output_queue_name
  region               = data.aws_region.current.name
  product_display_name = var.product_alias
  is_production        = var.env_alias == "prod"

  fifo_queue                  = true
  content_based_deduplication = false
  deduplication_scope         = "messageGroup"
  fifo_throughput_limit       = "perMessageGroupId"

  visibility_timeout_seconds    = var.queue_config.output_queue_visibility_timeout
  message_retention_seconds     = var.queue_config.output_queue_message_retention_seconds
  max_message_size              = var.queue_config.max_message_size
  receive_wait_time_seconds     = var.queue_config.receive_wait_time_seconds
  max_receive_count             = var.queue_config.output_queue_max_receive_count
  create_dlq                    = var.queue_config.output_queue_create_dlq
  dlq_message_retention_seconds = var.queue_config.output_queue_dlq_message_retention_seconds

  sqs_managed_sse_enabled = var.queue_config.sqs_managed_sse_enabled

  enable_producer_access = false
  enable_consumer_access = false

  tags = merge(var.tags, { Type = "OutputQueue" })
}
