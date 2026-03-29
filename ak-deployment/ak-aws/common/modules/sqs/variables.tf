data "aws_region" "current" {}

variable "product_alias" {
  type        = string
  description = "Product alias"
}

variable "region" {
  type        = string
  default     = null
  description = "Region where the resource(s) will be managed. Defaults to the Region set in the provider configuration"
}

variable "env_alias" {
  type        = string
  description = "Environment alias"
}

variable "module_name" {
  type        = string
  description = "Module name for queue identification"
}

variable "queue_name" {
  type        = string
  description = "Queue name suffix"
}

variable "product_display_name" {
  type        = string
  description = "Product display name"
}

variable "is_production" {
  type        = bool
  description = "Whether this is a production environment"
}

variable "max_message_size" {
  type        = number
  default     = null
  description = "The limit of how many bytes a message can contain before Amazon SQS rejects it. An integer from 1024 bytes (1 KiB) up to 1048576 bytes (1024 KiB)."
}

variable "message_retention_seconds" {
  type        = number
  default     = null
  description = "The number of seconds Amazon SQS retains a message. Integer representing seconds, from 60 (1 minute) to 1209600 (14 days)"
}

variable "visibility_timeout_seconds" {
  type        = number
  default     = null
  description = "The visibility timeout for the queue. An integer from 0 to 43200 (12 hours)"
}

variable "receive_wait_time_seconds" {
  type        = number
  default     = null
  description = "The time for which a ReceiveMessage call will wait for a message to arrive (long polling) before returning. An integer from 0 to 20 (seconds)"
}

variable "delay_seconds" {
  type        = number
  default     = null
  description = "The time in seconds that the delivery of all messages in the queue will be delayed. An integer from 0 to 900 (15 minutes)"
}

variable "max_receive_count" {
  type        = number
  default     = 5
  description = "Number of times a message can be received before being sent to DLQ"
}

variable "dlq_message_retention_seconds" {
  type        = number
  default     = null
  description = "The number of seconds Amazon SQS retains a message in the dead letter queue. Integer representing seconds, from 60 (1 minute) to 1209600 (14 days)"
}

variable "fifo_throughput_limit" {
  type        = string
  default     = null
  description = "Specifies whether the FIFO queue throughput quota applies to the entire queue or per message group"
}

# Queue type configuration
variable "fifo_queue" {
  type        = bool
  default     = false
  description = "Boolean designating a FIFO queue"
}

variable "create_dlq" {
  type        = bool
  default     = false
  description = "Determines whether to create SQS dead letter queue"
}

variable "content_based_deduplication" {
  type        = bool
  default     = null
  description = "Enables content-based deduplication for FIFO queues"
}

variable "deduplication_scope" {
  type        = string
  default     = null
  description = "Specifies whether message deduplication occurs at the message group or queue level"
}

# Encryption configuration
variable "sqs_managed_sse_enabled" {
  type        = bool
  default     = true
  description = "Boolean to enable server-side encryption (SSE) of message content with SQS-owned encryption keys"
}

variable "kms_master_key_id" {
  type        = string
  default     = null
  description = "The ID of an AWS-managed customer master key (CMK) for Amazon SQS or a custom CMK"
}

variable "kms_data_key_reuse_period_seconds" {
  type        = number
  default     = null
  description = "The length of time, in seconds, for which Amazon SQS can reuse a data key to encrypt or decrypt messages before calling AWS KMS again. An integer representing seconds, between 60 seconds (1 minute) and 86,400 seconds (24 hours)"
}

variable "tags" {
  type        = map(string)
  default     = {}
  description = "A mapping of tags to assign to all resources"
}

# Producer configuration
variable "enable_producer_access" {
  type        = bool
  default     = true
  description = "Enable IAM policy for producers"
}

variable "producer_arns" {
  type        = list(string)
  default     = []
  description = "ARNs of producers (Lambda functions, ECS tasks, EC2 instances) allowed to send messages"
}

# Consumer configuration
variable "enable_consumer_access" {
  type        = bool
  default     = true
  description = "Enable IAM policy for consumers"
}

variable "consumer_role_arns" {
  type        = list(string)
  default     = []
  description = "ARNs of consumer roles (Lambda execution role, ECS task role) allowed to receive messages"
}