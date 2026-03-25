# WebSocket API Gateway Module Variables

variable "region" {
  type        = string
  description = "AWS region"
}

variable "product_alias" {
  type        = string
  description = "Product alias for resource naming"
}

variable "env_alias" {
  type        = string
  description = "Environment alias for resource naming"
}

variable "product_display_name" {
  type        = string
  description = "Product display name"
  default     = "An Agent Kernel deployment"
}

variable "tags" {
  type        = map(string)
  description = "Tags to apply to resources"
  default     = {}
}

variable "lambda_function_invoke_arn" {
  type        = string
  description = "Invoke ARN of the Lambda function"
}

variable "lambda_function_name" {
  type        = string
  description = "Name of the Lambda function"
}

variable "cloudwatch_kms_key_arn" {
  type        = string
  description = "KMS key ARN for CloudWatch logs encryption"
  default     = null
}

variable "stage_name" {
  type        = string
  description = "WebSocket API stage name"
  default     = "prod"
}

variable "api_name_suffix" {
  type        = string
  description = "Suffix for the WebSocket API name"
  default     = "websocket-api"
}

variable "route_selection_expression" {
  type        = string
  description = "Route selection expression for WebSocket API"
  default     = "$request.body.action"
}

variable "log_retention_days" {
  type        = number
  description = "CloudWatch log retention in days"
  default     = 14
}

variable "throttling_burst_limit" {
  type        = number
  description = "Throttling burst limit for WebSocket API"
  default     = 5000
}

variable "throttling_rate_limit" {
  type        = number
  description = "Throttling rate limit for WebSocket API"
  default     = 2000
}

variable "logging_level" {
  type        = string
  description = "Logging level for WebSocket API"
  default     = "INFO"
  validation {
    condition     = contains(["OFF", "ERROR", "INFO"], var.logging_level)
    error_message = "Logging level must be one of: OFF, ERROR, INFO."
  }
}

variable "data_trace_enabled" {
  type        = bool
  description = "Enable data trace for WebSocket API"
  default     = true
}

variable "detailed_metrics_enabled" {
  type        = bool
  description = "Enable detailed metrics for WebSocket API"
  default     = true
}

variable "auto_deploy" {
  type        = bool
  description = "Enable auto deploy for WebSocket API stage"
  default     = true
}