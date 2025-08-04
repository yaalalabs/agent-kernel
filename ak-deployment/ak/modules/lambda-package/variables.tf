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

variable "is_production" {
  description = "Is production"
  type        = bool
  default     = false
}

variable "package_dir_path" {
  type        = string
  description = "Lambda function / layer path"
}

variable "module_name" {
  type        = string
  description = "module name"
}

variable "is_layer" {
  description = "is the package a layer"
  type        = bool
  default     = false
}

data "aws_caller_identity" "current" {}
