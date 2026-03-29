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
    input_queue_name                = optional(string, "input-queue") # Queue name suffix
    output_queue_name               = optional(string, "output-queue") # Queue name suffix
    
    # Input queue configuration
    input_queue_visibility_timeout  = optional(number, 60) # Visibility timeout for messages
    input_queue_max_receive_count   = optional(number, 5) # Number of times a message can be received before being sent to DLQ
    input_queue_message_retention_seconds = optional(number, 3600) # How long messages remain in the queue (default: 1 hour)
    input_queue_max_message_size    = optional(number, 262144) # Maximum message size in bytes (default: 256KB)
    input_queue_receive_wait_time_seconds = optional(number, 0) # The time for which a ReceiveMessage call will wait for a message to arrive (long polling)
    input_queue_delay_seconds       = optional(number, 0) # The time in seconds that the delivery of all messages in the queue will be delayed
    input_queue_create_dlq          = optional(bool, false) # Whether to create a dead letter queue
    input_queue_dlq_message_retention_seconds = optional(number, 3600) # How long messages remain in DLQ (default: 1 hour)
    
    # Output queue configuration
    output_queue_visibility_timeout = optional(number, 60) # Visibility timeout for messages
    output_queue_max_receive_count  = optional(number, 5) # Number of times a message can be received before being sent to DLQ
    output_queue_message_retention_seconds = optional(number, 3600) # How long messages remain in the queue (default: 1 hour)
    output_queue_max_message_size   = optional(number, 262144) # Maximum message size in bytes (default: 256KB)
    output_queue_receive_wait_time_seconds = optional(number, 0) # The time for which a ReceiveMessage call will wait for a message to arrive (long polling)
    output_queue_delay_seconds      = optional(number, 0) # The time in seconds that the delivery of all messages in the queue will be delayed
    output_queue_create_dlq         = optional(bool, false) # Whether to create a dead letter queue
    output_queue_dlq_message_retention_seconds = optional(number, 3600) # How long messages remain in DLQ (default: 1 hour)
    
    # Common queue configuration
    fifo_queue                      = optional(bool, true) # Whether to create a FIFO queue (true) or standard queue (false)
    sqs_managed_sse_enabled         = optional(bool, true) # Enable SQS-managed server-side encryption (SSE). When true, KMS variables are ignored. Set to false only if using customer-managed KMS encryption
    kms_master_key_id               = optional(string, null) # Required only when sqs_managed_sse_enabled = false. The ARN or ID of a customer-managed KMS key for Amazon SQS encryption
    kms_data_key_reuse_period_seconds = optional(number, null) # Required only when sqs_managed_sse_enabled = false. The length of time in seconds for which Amazon SQS can reuse a data key (60-86400)
    
    # FIFO-specific configuration (only used when fifo_queue = true)
    content_based_deduplication     = optional(bool, false) # Enable content-based deduplication. For chat systems, set to false and use explicit MessageDeduplicationId in your application instead. With content-based dedup, identical messages within 5 minutes are rejected
    fifo_throughput_limit           = optional(string, "perMessageGroupId") # FIFO throughput limit: 'perMessageGroupId' or 'perQueue'
    deduplication_scope             = optional(string, "messageGroup") # Deduplication scope: 'queue' (deduplication across entire queue) or 'messageGroup' (deduplication per message group). Use 'messageGroup' for chat systems where MessageGroupId=thread_id
    
    # Access control
    enable_producer_access          = optional(bool, true) # Enable IAM policy for producers
    producer_arns                   = optional(list(string), []) # ARNs of producers (Lambda functions, ECS tasks, EC2 instances) allowed to send messages
    enable_consumer_access          = optional(bool, true) # Enable IAM policy for consumers
    consumer_role_arns              = optional(list(string), []) # ARNs of consumer roles (Lambda execution role, ECS task role) allowed to receive messages
  })
  default = {}
}