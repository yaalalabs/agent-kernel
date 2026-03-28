# Input Queue
module "input_queue" {
  source = "../../../common/modules/sqs"

  product_alias         = var.product_alias
  env_alias            = var.env_alias
  module_name          = var.module_name
  queue_name           = coalesce(var.queue_config.input_queue_name, "input-queue")
  region               = data.aws_region.current.name
  product_display_name = var.product_alias
  is_production        = var.env_alias == "prod"

  # Queue configuration from queue_config variable with defaults
  fifo_queue                    = coalesce(var.queue_config.fifo_queue, false)
  max_message_size             = coalesce(var.queue_config.input_queue_max_message_size, 262144)
  message_retention_seconds    = coalesce(var.queue_config.input_queue_message_retention_seconds, 1209600)
  visibility_timeout_seconds   = coalesce(var.queue_config.input_queue_visibility_timeout, 60)
  receive_wait_time_seconds    = coalesce(var.queue_config.input_queue_receive_wait_time_seconds, 20)
  delay_seconds               = coalesce(var.queue_config.input_queue_delay_seconds, 0)
  max_receive_count           = coalesce(var.queue_config.input_queue_max_receive_count, 5)
  create_dlq                  = coalesce(var.queue_config.input_queue_create_dlq, false)
  dlq_message_retention_seconds = coalesce(var.queue_config.input_queue_dlq_message_retention_seconds, 1209600)

  # FIFO-specific configuration
  content_based_deduplication = coalesce(var.queue_config.content_based_deduplication, false)
  fifo_throughput_limit      = coalesce(var.queue_config.fifo_throughput_limit, "perQueueGroup")
  deduplication_scope        = coalesce(var.queue_config.deduplication_scope, "messageGroup")

  # Encryption
  sqs_managed_sse_enabled         = coalesce(var.queue_config.sqs_managed_sse_enabled, true)
  kms_master_key_id               = var.queue_config.kms_master_key_id
  kms_data_key_reuse_period_seconds = var.queue_config.kms_data_key_reuse_period_seconds

  # Access control
  enable_producer_access = coalesce(var.queue_config.enable_producer_access, false)
  producer_arns         = coalesce(var.queue_config.producer_arns, [])
  enable_consumer_access = coalesce(var.queue_config.enable_consumer_access, false)
  consumer_role_arns    = coalesce(var.queue_config.consumer_role_arns, [])

  tags = merge(var.tags, {
    Type = "InputQueue"
  })
}

# Output Queue
module "output_queue" {
  source = "../../../common/modules/sqs"

  product_alias         = var.product_alias
  env_alias            = var.env_alias
  module_name          = var.module_name
  queue_name           = coalesce(var.queue_config.output_queue_name, "output-queue")
  region               = data.aws_region.current.name
  product_display_name = var.product_alias
  is_production        = var.env_alias == "prod"

  # Queue configuration from queue_config variable with defaults
  fifo_queue                    = coalesce(var.queue_config.fifo_queue, false)
  max_message_size             = coalesce(var.queue_config.output_queue_max_message_size, 262144)
  message_retention_seconds    = coalesce(var.queue_config.output_queue_message_retention_seconds, 1209600)
  visibility_timeout_seconds   = coalesce(var.queue_config.output_queue_visibility_timeout, 60)
  receive_wait_time_seconds    = coalesce(var.queue_config.output_queue_receive_wait_time_seconds, 20)
  delay_seconds               = coalesce(var.queue_config.output_queue_delay_seconds, 0)
  max_receive_count           = coalesce(var.queue_config.output_queue_max_receive_count, 5)
  create_dlq                  = coalesce(var.queue_config.output_queue_create_dlq, false)
  dlq_message_retention_seconds = coalesce(var.queue_config.output_queue_dlq_message_retention_seconds, 1209600)

  # FIFO-specific configuration
  content_based_deduplication = coalesce(var.queue_config.content_based_deduplication, false)
  fifo_throughput_limit      = coalesce(var.queue_config.fifo_throughput_limit, "perQueueGroup")
  deduplication_scope        = coalesce(var.queue_config.deduplication_scope, "messageGroup")

  # Encryption
  sqs_managed_sse_enabled         = coalesce(var.queue_config.sqs_managed_sse_enabled, true)
  kms_master_key_id               = var.queue_config.kms_master_key_id
  kms_data_key_reuse_period_seconds = var.queue_config.kms_data_key_reuse_period_seconds

  # Access control
  enable_producer_access = coalesce(var.queue_config.enable_producer_access, false)
  producer_arns         = coalesce(var.queue_config.producer_arns, [])
  enable_consumer_access = coalesce(var.queue_config.enable_consumer_access, false)
  consumer_role_arns    = coalesce(var.queue_config.consumer_role_arns, [])

  tags = merge(var.tags, {
    Type = "OutputQueue"
  })
}

data "aws_region" "current" {}