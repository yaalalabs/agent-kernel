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

variable "module_type" {
  type        = string
  description = "Module type (python or nodejs)"
  default     = "python"
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