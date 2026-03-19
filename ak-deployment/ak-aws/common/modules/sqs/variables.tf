data "aws_region" "current" {}

variable "product_alias" {
  type        = string
  description = "Product alias"
}

variable "region" {
  description = "AWS region"
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
  default     = 262144
  description = "Maximum message size in bytes (default: 256KB)"
}

variable "message_retention_seconds" {
  type        = number
  default     = 3600
  description = "How long messages remain in the queue (default: 1 hour)"
}

variable "visibility_timeout_seconds" {
  type        = number
  default     = 60
  description = "Visibility timeout for messages"
}

variable "max_receive_count" {
  type        = number
  default     = 5
  description = "Number of times a message can be received before being sent to DLQ"
}

variable "dlq_message_retention_seconds" {
  type        = number
  default     = 3600
  description = "How long messages remain in DLQ (default: 1 hour)"
}

variable "fifo_throughput_limit" {
  type        = string
  default     = "perQueueGroup"
  description = "FIFO throughput limit: 'perQueueGroup' or 'perQueue'"
}

variable "content_based_deduplication" {
  type        = bool
  default     = false
  description = "Enable content-based deduplication. For chat systems, set to false and use explicit MessageDeduplicationId in your application instead. With content-based dedup, identical messages within 5 minutes are rejected"
}

variable "deduplication_scope" {
  type        = string
  default     = "messageGroup"
  description = "Deduplication scope: 'queue' (deduplication across entire queue) or 'messageGroup' (deduplication per message group). Use 'messageGroup' for chat systems where MessageGroupId=thread_id"
}

# Encryption configuration
variable "sqs_managed_sse_enabled" {
  type        = bool
  default     = true
  description = "Enable SQS-managed server-side encryption (SSE). When true, KMS variables are ignored. Set to false only if using customer-managed KMS encryption"
}

variable "kms_master_key_id" {
  type        = string
  default     = null
  description = "Required only when sqs_managed_sse_enabled = false. The ARN or ID of a customer-managed KMS key for Amazon SQS encryption"
}

variable "kms_data_key_reuse_period_seconds" {
  type        = number
  default     = null
  description = "Required only when sqs_managed_sse_enabled = false. The length of time in seconds for which Amazon SQS can reuse a data key (60-86400)"
}

variable "tags" {
  type        = map(string)
  default     = {}
  description = "A map of tags to add"
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