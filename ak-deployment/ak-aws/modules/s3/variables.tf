data "aws_region" "current" {}

data "aws_caller_identity" "current" {}

variable "product_alias" {
  type        = string
  description = "Product alias"
}

variable "region" {
  description = "AWS region"
}

variable "env_alias" {
  type        = string
  description = "Environment alias"
}

variable "product_display_name" {
  type        = string
  description = "Product display name"
}

variable "s3_bucket_tags" {
  description = "A map of tags to add"
  type = map(string)
  default = {}
}

variable "s3_kms_key_id" {
  type = string
  default = null
}

variable "is_production" {
  type = bool
}
