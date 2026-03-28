# API Gateway Module Variables

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

variable "api_base_path" {
  type        = string
  description = "Base path for the API"
}

variable "api_version" {
  type        = string
  description = "API version"
}

variable "agent_endpoint" {
  type        = string
  description = "Agent endpoint path"
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

variable "endpoints" {
  description = "List of API endpoint objects"
  type = list(object({
    path   = string
    method = string
  }))
  default = []
}

variable "authorizer" {
  description = "Authorizer configuration object"
  type = object({
    function_name         = string
    handler_path          = string
    package_type          = string
    package_path          = string
    module_name           = string
    result_ttl_in_seconds = optional(number, 300)
  })
  default = null
}

variable "authorizer_lambda_function_invoke_arn" {
  type        = string
  description = "Invoke ARN of the authorizer Lambda function"
  default     = ""
}

variable "authorizer_lambda_function_name" {
  type        = string
  description = "Name of the authorizer Lambda function"
  default     = ""
}

variable "create_authorizer" {
  type        = bool
  description = "Whether to create the authorizer"
  default     = false
}

variable "cloudwatch_kms_key_arn" {
  type        = string
  description = "KMS key ARN for CloudWatch logs encryption"
  default     = null
}
