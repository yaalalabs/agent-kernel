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
  description = "Region"
}

variable "module_type" {
  type        = string
  description = "Module type (python or nodejs)"
  default     = "python"
}

variable "source_bucket" {
  type        = string
  description = "S3 bucket used to store the agent runner source package"
  default     = null
}

variable "docker_image_uri" {
  type        = string
  description = "Docker image URI for Image package type"
  default     = null
}

variable "create_dynamodb_memory_table" {
  type        = bool
  description = "Create a dynamodb table to store the Agent memory"
  default     = false
}

variable "create_dynamodb_multimodal_memory_table" {
  type        = bool
  description = "Create a dynamodb table to store the Agent multimodal memory"
  default     = false
}

variable "dynamodb_memory_table_arn" {
  type        = string
  description = "ARN of the DynamoDB memory table"
  default     = null
}

variable "dynamodb_memory_table_name" {
  type        = string
  description = "Name of the DynamoDB memory table"
  default     = null
}

variable "dynamodb_multimodal_memory_table_arn" {
  type        = string
  description = "ARN of the DynamoDB multimodal memory table"
  default     = null
}

variable "dynamodb_multimodal_memory_table_name" {
  type        = string
  description = "Name of the DynamoDB multimodal memory table"
  default     = null
}

variable "redis_url" {
  type        = string
  description = "URL of the Redis cluster"
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

variable "agent_runner" {
  description = "Agent runner configuration object"
  type = object({
    function_name         = optional(string, "agent-runner")
    function_description   = optional(string, "Agent runner Lambda for processing input queue messages")
    timeout               = optional(number, 30)
    memory_size           = optional(number, 512)
    package_path          = string
    package_type          = optional(string, "LocalZip")
    handler_path          = optional(string, "agent_runner.handler")
    module_name           = optional(string, null)
    layers                = optional(list(string), [])
    environment_variables = optional(map(string), {})
  })
}

variable "queue_config" {
  description = "Queue configuration object"
  type = object({
    input_queue_arn                        = string
    output_queue_arn                       = string
    output_queue_url                       = string
    batch_size                             = optional(number, 10)
    maximum_batching_window_in_seconds     = optional(number, 5)
  })
}

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