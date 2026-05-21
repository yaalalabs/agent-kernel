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

variable "product_alias" {
  type        = string
  description = "Product alias for resource naming"
}

variable "env_alias" {
  type        = string
  description = "Environment alias for resource naming"
}

variable "region" {
  type        = string
  description = "AWS region for S3 path construction"
}

variable "source_bucket" {
  type        = string
  description = "S3 bucket used for S3 ZIP deployment"
  default     = null
}

variable "docker_image_uri" {
  type        = string
  description = "Docker image URI for Image package type"
  default     = null
}

variable "is_production" {
  description = "Is production"
  type        = bool
  default     = false
}

variable "lambda_signer_profile_name" {
  type        = string
  description = "AWS Signer profile name"
  default     = "sample_profile"
}

variable "lambda_signing_config_arn" {
  type        = string
  description = "ARN of the Lambda code signing configuration"
  default     = null
}

variable "response_handler" {
  description = "Response handler configuration object"
  type = object({
    function_name         = optional(string, "response-handler")
    function_description   = optional(string, "Response handler Lambda for processing SQS messages and storing responses")
    timeout               = optional(number, 30)
    memory_size           = optional(number, 256)
    handler_path          = optional(string, "response_handler.handler")
    module_name           = optional(string, "response-handler")
    package_path          = optional(string, null)
    package_type          = optional(string, "LocalZip")
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
    output_queue_arn                   = string
    output_queue_max_receive_count     = optional(number, 5)
    batch_size                         = optional(number, 10)
    maximum_batching_window_in_seconds = optional(number, 5)
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

variable "websocket_connections_dynamodb" {
  description = "DynamoDB configuration for websocket connections table"
  type = object({
    table_name = string
    table_arn  = string
  })
  default = null
}

variable "websocket_api_execution_arn" {
  description = "Execution ARN of the WebSocket API Gateway (for PostToConnection permission)"
  type        = string
  default     = null
}

variable "websocket_mode" {
  description = "Whether WebSocket API is enabled (known at plan time)"
  type        = bool
  default     = false
}

