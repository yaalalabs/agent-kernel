# API Gateway Module Variables

variable "region" {
  type        = string
  description = "AWS region"
}

variable "prefix" {
  type        = string
  description = "Prefix applied to every resource name (e.g. \"myproduct-dev-agents\")"
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

variable "proxy_routes" {
  description = <<-EOT
    Names of the {proxy+} routes to create under the base path and version, for example ["a2a", "mcp"]. Each name creates
    /<name> and /<name>/{proxy+}, both answering every method (ANY) and both integrated with the request-handler Lambda, so
    a path of any depth below /<name> reaches it. The existing `endpoints` list allows three path levels and no catch-all,
    which is why these are separate. Empty by default: an existing deployment plans no change.
  EOT
  type        = list(string)
  default     = []

  validation {
    condition     = alltrue([for name in var.proxy_routes : can(regex("^[a-z][a-z0-9-]*$", name))])
    error_message = "Each proxy_routes entry must be a lowercase path segment (letters, digits and hyphens, starting with a letter), such as \"a2a\"."
  }

  validation {
    condition     = length(distinct(var.proxy_routes)) == length(var.proxy_routes)
    error_message = "proxy_routes must not list a name twice."
  }
}

variable "authorizer" {
  description = "Authorizer configuration object"
  type = object({
    function_name         = string
    handler_path          = string
    package_type          = string
    package_path          = string
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

variable "enable_api_gateway_logs" {
  type        = bool
  description = "Whether to create the CloudWatch log group and enable access logging for the API Gateway stage"
  default     = false
}

variable "cloudwatch_kms_key_arn" {
  type        = string
  description = "KMS key ARN for CloudWatch logs encryption"
  default     = null
}
