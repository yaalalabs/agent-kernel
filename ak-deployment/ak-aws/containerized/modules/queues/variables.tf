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

variable "queue_config" {
  description = "Queue configuration object"
  type = object({
    # Queue names
    input_queue_name  = optional(string, "input-queue")
    output_queue_name = optional(string, "output-queue")

    # Shared settings
    sqs_managed_sse_enabled    = optional(bool, true)
    max_message_size           = optional(number, 262144)
    receive_wait_time_seconds  = optional(number, 0)
    
    # Input queue settings
    input_queue_visibility_timeout           = optional(number, 60)
    input_queue_message_retention_seconds    = optional(number, 1800)
    input_queue_max_receive_count            = optional(number, 5)
    input_queue_create_dlq                   = optional(bool, false)
    input_queue_dlq_message_retention_seconds = optional(number, 1800)
    
    # Output queue settings
    output_queue_visibility_timeout            = optional(number, 60)
    output_queue_message_retention_seconds     = optional(number, 1800)
    output_queue_max_receive_count             = optional(number, 5)
    output_queue_create_dlq                    = optional(bool, false)
    output_queue_dlq_message_retention_seconds = optional(number, 1800)
  })
}

variable "tags" {
  type        = map(string)
  description = "Resource tags"
  default     = {}
}
