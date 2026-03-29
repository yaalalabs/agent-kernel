variable "product_alias" {
  type        = string
  description = "Product alias for resource naming"
}

variable "env_alias" {
  type        = string
  description = "Environment alias for resource naming"
}

variable "module_name" {
  type        = string
  description = "Module name for resource naming"
}

variable "tags" {
  type        = map(string)
  description = "Resource tags"
  default     = {}
}

variable "queue_config" {
  description = "Queue configuration object"
  type = object({
    # Queue names
    input_queue_name                = optional(string, "input-queue")
    output_queue_name               = optional(string, "output-queue")
    
    # Input queue configuration
    input_queue_visibility_timeout  = optional(number, 60)
    input_queue_max_receive_count   = optional(number, 5)
    input_queue_message_retention_seconds = optional(number, 3600)
    input_queue_max_message_size    = optional(number, 262144)
    input_queue_receive_wait_time_seconds = optional(number, 0)
    input_queue_delay_seconds       = optional(number, 0)
    input_queue_create_dlq          = optional(bool, false)
    input_queue_dlq_message_retention_seconds = optional(number, 3600)
    
    # Output queue configuration
    output_queue_visibility_timeout = optional(number, 60)
    output_queue_max_receive_count  = optional(number, 5)
    output_queue_message_retention_seconds = optional(number, 3600)
    output_queue_max_message_size   = optional(number, 262144)
    output_queue_receive_wait_time_seconds = optional(number, 0)
    output_queue_delay_seconds      = optional(number, 0)
    output_queue_create_dlq         = optional(bool, false)
    output_queue_dlq_message_retention_seconds = optional(number, 3600)
    
    # Common queue configuration
    fifo_queue                      = optional(bool, true)
    sqs_managed_sse_enabled         = optional(bool, true)
    kms_master_key_id               = optional(string, null)
    kms_data_key_reuse_period_seconds = optional(number, null)
    
    # FIFO-specific configuration (only used when fifo_queue = true)
    content_based_deduplication     = optional(bool, false)
    fifo_throughput_limit           = optional(string, "perQueueGroup")
    deduplication_scope             = optional(string, "messageGroup")
    
    # Access control
    enable_producer_access          = optional(bool, true)
    producer_arns                   = optional(list(string), [])
    enable_consumer_access          = optional(bool, true)
    consumer_role_arns              = optional(list(string), [])
  })
  default = {}
}