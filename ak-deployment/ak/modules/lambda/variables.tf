variable "region" {
  type        = string
  description = "Region"
  default     = "ap-southeast-2"
}

variable "product_alias" {
  type        = string
  description = "Product alias"
}

variable "env_alias" {
  type        = string
  description = "Environment alias"
}

variable "product_display_name" {
  type        = string
  description = "Product display name"
}

variable "module_type" {
  type        = string
  description = "Module type"
  default     = "python"
}

variable "module_name" {
  type        = string
  description = "module name"
}

variable "is_production" {
  description = "Is production"
  type        = bool
  default     = false
}

# variable "package_path" {
#   type        = string
#   description = "Lambda function path"
# }

variable "mode" {
  type        = string
  description = "['install', 'upgrade']"
}

variable "setup" {
  description = "Setup type (env or tenant)"
  type        = string
}

variable "tenant" {
  description = "Tenant identifier"
  type        = string
  default     = "UNSPECIFIED"
}

variable "event_source_mapping" {
  description = "Event source mapping"
  type        = any
  default     = null
}


variable "environment_variables" {
  description = "Environment variables"
  type        = any
  default     = null
}

variable "timeout" {
  description = "Lambda timeout"
  type        = number
  default     = 10
}

variable "memory_size" {
  description = "Lambda memory size"
  type        = number
  default     = 128
}

variable "function_name" {
  description = "Lambda function name"
  type        = string
}

variable "function_description" {
  description = "Lambda function description"
  type        = string
}

variable "handler_path" {
  description = "Lambda handler path"
  type        = string
}

variable "role_arn" {
  description = "Lambda role ARN"
  type        = string
}

variable "image_uri" {
  description = "Image URI for docker based lambdas"
  type        = string
  default     = null
}

variable "package_type" {
  description = "Lambda deployment type"
  type        = string
  default     = "Zip"
}


variable "layers" {
  description = "Lambda layers"
  type        = list(string)
  default     = []
}

data "aws_caller_identity" "current" {}
