variable "prefix" {
  type        = string
  description = "Prefix applied to every resource name (e.g. \"myproduct-dev-agents\")"
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

variable "is_production" {
  description = "Is production"
  type        = bool
  default     = false
}

variable "vpc_id" {
  type        = string
  description = "VPC ID"
  default     = null
}

variable "subnet_ids" {
  type        = list(string)
  description = "Subnet IDs for VPC deployment"
  default     = []
}

variable "security_group_id" {
  type        = string
  description = "Shared security group ID used for Lambda VPC networking"
  default     = ""
}

variable "lambda_kms_key_arn" {
  type        = string
  description = "ARN of the KMS key for Lambda encryption"
  default     = null
}

variable "cloudwatch_kms_key_arn" {
  type        = string
  description = "ARN of the KMS key for CloudWatch logs encryption"
  default     = null
}

variable "tags" {
  type        = map(string)
  description = "Tags to apply to resources"
  default     = {}
}

# WebSocket Connection Table ARN (for IAM permissions)
variable "websocket_connection_table_arn" {
  type        = string
  description = "ARN of the DynamoDB table for WebSocket connection mapping (for IAM permissions)"
}

# WebSocket Connection Handler Configuration
variable "ws_connection_handler" {
  description = "WebSocket connection handler configuration object"
  type = object({
    function_name         = optional(string, "ws-connection-handler")
    function_description  = optional(string, "WebSocket connection handler Lambda for $connect and $disconnect routes")
    timeout               = optional(number, 30)
    memory_size           = optional(number, 256)
    handler_path          = optional(string, "ws_connection_handler.handler")
    package_path          = string
    layers                = optional(list(string), [])
    cloudwatch_logs_retention_in_days = optional(number, 90)
    environment_variables = optional(map(string), {})
  })
}

variable "account_id" {
  type        = string
  description = "AWS account ID, used to scope the SSM Parameter Store IAM resource ARN"
  default     = null
}

variable "ssm_enabled" {
  type        = bool
  description = "Whether the application roles may read /ak/<prefix>/* from SSM Parameter Store and receive AK_SECRET__PREFIX"
  default     = false
}
