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

variable "stage_name" {
  type        = string
  description = "WebSocket API stage name"
  default     = "agents"
}

variable "tags" {
  type        = map(string)
  description = "Tags to apply to resources"
  default     = {}
}

variable "chat_route" {
  type        = string
  description = "WebSocket route for chat messages"
  validation {
    condition     = !strcontains(var.chat_route, "/")
    error_message = "chat_route cannot contain '/' character. Route names must not include slashes."
  }
}

variable "custom_routes" {
  type = list(object({
    route = string
  }))
  description = "List of custom WebSocket routes to add. Each object should have a 'route' key with the custom route name."
  default     = []
  validation {
    condition = alltrue([
      for route_obj in var.custom_routes : !strcontains(route_obj.route, "/")
    ])
    error_message = "custom_routes cannot contain '/' character in any route name. Route names must not include slashes."
  }
}

variable "route_handler_lambda_invoke_arn" {
  type        = string
  description = "Invoke ARN of the routes handler Lambda function (for $default and custom routes)"
}

variable "route_handler_lambda_name" {
  type        = string
  description = "Name of the routes handler Lambda function"
}

variable "route_handler_lambda_role_name" {
  type        = string
  description = "IAM role name of the routes handler Lambda function (for PostToConnection permission)"
  default     = null
}

variable "connection_handler_lambda_invoke_arn" {
  type        = string
  description = "Invoke ARN of the connection handler Lambda function (for $connect and $disconnect routes)"
}

variable "connection_handler_lambda_name" {
  type        = string
  description = "Name of the connection handler Lambda function"
}

variable "enable_data_trace" {
  type        = bool
  description = "Enable data trace logging for WebSocket API"
  default     = false
}

variable "logging_level" {
  type        = string
  description = "Logging level for WebSocket API (ERROR, INFO, OFF)"
  default     = "ERROR"
}

variable "enable_detailed_metrics" {
  type        = bool
  description = "Enable detailed metrics for WebSocket API"
  default     = false
}

variable "cloudwatch_logs_retention_in_days" {
  type        = number
  description = "Retention period in days for CloudWatch logs"
  default     = 90
}

variable "cloudwatch_kms_key_arn" {
  type        = string
  description = "KMS key ARN for CloudWatch logs encryption"
  default     = null
}
