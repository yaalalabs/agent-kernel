# Response Handler Module Variables

variable "package_path" {
  type        = string
  description = "Path to the response handler Lambda deployment package"
}

variable "module_type" {
  type        = string
  description = "Module type"
  default     = "python"
}

variable "package_type" {
  type        = string
  description = "Lambda deployment package type"
  default     = "LocalZip"
}

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

variable "response_handler" {
  description = "Response handler configuration object"
  type = object({
    function_name         = optional(string, "response-handler")
    timeout               = optional(number, 60)
    memory_size           = optional(number, 256)
    handler_path          = optional(string, "response_handler.handler")
    layers                = optional(list(string), [])
    environment_variables = optional(map(string), {})
  })
}

variable "response_store" {
  description = "Response store configuration object"
  type = object({
    redis = optional(object({
      prefix = string
      url    = string
      ttl    = number
    }), null)
    dynamodb = optional(object({
      table_name = string
      table_arn = string
      ttl        = number
    }), null)
  })
  default = null
  validation {
    condition = var.response_store == null ? true : (
      (var.response_store.redis != null && var.response_store.dynamodb == null) ||
      (var.response_store.dynamodb != null && var.response_store.redis == null)
    )
    error_message = "Exactly one of redis or dynamodb must be configured when response_store is provided."
  }
}

variable "queue_config" {
  description = "Queue configuration object"
  type = object({
    output_queue_arn                       = string
    batch_size                             = optional(number, 10)
    maximum_batching_window_in_seconds     = optional(number, 5)
  })
}

# Local variables that need to be passed from parent module
variable "subnet_ids" {
  type        = list(string)
  description = "VPC subnet IDs"
  default     = []
}

variable "security_group_id" {
  type        = string
  description = "Security group ID for Lambda"
  default     = ""
}

variable "lambda_kms_key_arn" {
  type        = string
  description = "KMS key ARN for Lambda encryption"
  default     = null
}

variable "cloudwatch_kms_key_arn" {
  type        = string
  description = "KMS key ARN for CloudWatch logs encryption"
  default     = null
}

variable "websocket_connections_table_name" {
  type        = string
  description = "Name of the WebSocket connections DynamoDB table"
  default     = null
}

variable "websocket_connections_table_arn" {
  type        = string
  description = "ARN of the WebSocket connections DynamoDB table"
  default     = null
}

variable "websocket_api_domain_name" {
  type        = string
  description = "Domain name of the WebSocket API"
  default     = null
}