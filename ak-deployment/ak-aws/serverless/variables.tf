variable "region" {
  type        = string
  description = "Region"
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
  default     = "An Agent Kernel deployment"
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

variable "package_path" {
  type        = string
  description = "Zip package path"
}


variable "event_source_mapping" {
  description = "Event source mapping"
  type        = any
  default = []
}

variable "environment_variables" {
  description = "Environment variables"
  type        = any
  default = {}
}

variable "timeout" {
  description = "Lambda timeout"
  type        = number
  default     = 30
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

variable "image_uri" {
  description = "Image URI for docker based lambdas"
  type        = string
  default     = null
}

variable "package_type" {
  description = "Lambda deployment type Image/LocalZip/S3Zip"
  type        = string
  default     = "LocalZip"
}


variable "layers" {
  description = "Lambda layers"
  type = list(string)
  default = []
}

variable "api_version" {
  type        = string
  description = "API version"
  default     = "v1"
}

variable "agent_endpoint" {
  type        = string
  description = "Agent invocation endpoint"
  default     = "chat"
}

variable "tags" {
  type = map(string)
  description = "Resource tags"
  default = {}
}


data "aws_caller_identity" "current" {}
