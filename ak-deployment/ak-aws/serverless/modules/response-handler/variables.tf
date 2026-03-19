# Response Handler Module Variables

variable "package_path" {
  type        = string
  description = "Path to the response handler Lambda deployment package"
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
    function_name = optional(string, "response-handler")
    timeout       = optional(number, 60)
    memory_size   = optional(number, 256)
  })
}

variable "response_store" {
  description = "Response store configuration object"
  type = object({
    database = string
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
    condition = var.response_store == null || contains(["redis", "dynamodb"], var.response_store.database)
    error_message = "Database must be either 'redis' or 'dynamodb' when response_store is not null."
  }
}

variable "environment_variables" {
  type        = map(string)
  description = "Environment variables for the Lambda function"
  default     = {}
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