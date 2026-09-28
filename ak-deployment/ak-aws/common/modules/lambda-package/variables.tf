variable "region" {
  type        = string
  description = "Region"
  default     = "ap-southeast-2"
}

variable "prefix" {
  type        = string
  description = "Prefix applied to every resource name (e.g. \"myproduct-dev-agents\")"
}

variable "product_display_name" {
  type        = string
  description = "Product display name"
  default     = null
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

variable "is_layer" {
  description = "is the package a layer"
  type        = bool
  default     = false
}
variable "s3_bucket" {
  description = "S3 bucket"
  type        = string
}

data "aws_caller_identity" "current" {}
