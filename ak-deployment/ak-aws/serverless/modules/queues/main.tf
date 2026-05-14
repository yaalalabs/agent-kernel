# Input Queue
module "input_queue" {
  source               = "yaalalabs/ak-common/aws//modules/sqs"
  version              = "0.4.0"

  product_alias        = var.product_alias
  env_alias            = var.env_alias
  module_name          = var.module_name
  queue_name           = var.queue_config.input_queue_name
  region               = data.aws_region.current.region
  product_display_name = var.product_alias
  is_production        = var.env_alias == "prod"

  # Queue configuration from queue_config variable with defaults
  fifo_queue                    = var.queue_config.fifo_queue
  max_message_size              = var.queue_config.input_queue_max_message_size
  message_retention_seconds     = var.queue_config.input_queue_message_retention_seconds
  visibility_timeout_seconds    = var.queue_config.input_queue_visibility_timeout
  receive_wait_time_seconds     = var.queue_config.input_queue_receive_wait_time_seconds
  delay_seconds                 = var.queue_config.input_queue_delay_seconds
  max_receive_count             = var.queue_config.input_queue_max_receive_count
  create_dlq                    = var.queue_config.input_queue_create_dlq
  dlq_message_retention_seconds = var.queue_config.input_queue_dlq_message_retention_seconds

  # FIFO-specific configuration
  content_based_deduplication = var.queue_config.content_based_deduplication
  fifo_throughput_limit       = var.queue_config.fifo_throughput_limit
  deduplication_scope         = var.queue_config.deduplication_scope

  # Encryption
  sqs_managed_sse_enabled           = var.queue_config.sqs_managed_sse_enabled
  kms_master_key_id                 = var.queue_config.kms_master_key_id
  kms_data_key_reuse_period_seconds = var.queue_config.kms_data_key_reuse_period_seconds

  # Access control
  enable_producer_access = var.queue_config.enable_producer_access
  producer_arns          = var.queue_config.producer_arns
  enable_consumer_access = var.queue_config.enable_consumer_access
  consumer_role_arns     = var.queue_config.consumer_role_arns

  tags = merge(var.tags, {
    Type = "InputQueue"
  })
}

# Output Queue
module "output_queue" {
  source               = "yaalalabs/ak-common/aws//modules/sqs"
  version              = "0.4.0"

  product_alias        = var.product_alias
  env_alias            = var.env_alias
  module_name          = var.module_name
  queue_name           = var.queue_config.output_queue_name
  region               = data.aws_region.current.region
  product_display_name = var.product_alias
  is_production        = var.env_alias == "prod"

  # Queue configuration from queue_config variable with defaults
  fifo_queue                    = var.queue_config.fifo_queue
  max_message_size              = var.queue_config.output_queue_max_message_size
  message_retention_seconds     = var.queue_config.output_queue_message_retention_seconds
  visibility_timeout_seconds    = var.queue_config.output_queue_visibility_timeout
  receive_wait_time_seconds     = var.queue_config.output_queue_receive_wait_time_seconds
  delay_seconds                 = var.queue_config.output_queue_delay_seconds
  max_receive_count             = var.queue_config.output_queue_max_receive_count
  create_dlq                    = var.queue_config.output_queue_create_dlq
  dlq_message_retention_seconds = var.queue_config.output_queue_dlq_message_retention_seconds

  # FIFO-specific configuration
  content_based_deduplication = var.queue_config.content_based_deduplication
  fifo_throughput_limit       = var.queue_config.fifo_throughput_limit
  deduplication_scope         = var.queue_config.deduplication_scope

  # Encryption
  sqs_managed_sse_enabled           = var.queue_config.sqs_managed_sse_enabled
  kms_master_key_id                 = var.queue_config.kms_master_key_id
  kms_data_key_reuse_period_seconds = var.queue_config.kms_data_key_reuse_period_seconds

  # Access control
  enable_producer_access = var.queue_config.enable_producer_access
  producer_arns          = var.queue_config.producer_arns
  enable_consumer_access = var.queue_config.enable_consumer_access
  consumer_role_arns     = var.queue_config.consumer_role_arns

  tags = merge(var.tags, {
    Type = "OutputQueue"
  })
}

data "aws_region" "current" {}
