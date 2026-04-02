# Response Handler Module Variables

variable "package_path" {
  type        = string
  description = "Path to the response handler Lambda deployment package"
}

variable "cloudwatch_logs_retention_in_days" {
  type        = number
  description = "CloudWatch log retention period in days"
  default     = 90
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
    function_description   = optional(string, "Response handler Lambda for processing SQS messages and storing responses")
    timeout               = optional(number, 30)
    memory_size           = optional(number, 256)
    handler_path          = optional(string, "response_handler.handler")
    layers                = optional(list(string), [])
    environment_variables = optional(map(string), {})
  })
}

variable "response_store_redis" {
  description = "Redis configuration for response storage"
  type = object({
    url = string
  })
  default = null
}

variable "response_store_dynamodb" {
  description = "DynamoDB configuration for response storage"
  type = object({
    table_name = string
    table_arn  = string
  })
  default = null
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
