variable "region" {
  type        = string
  description = "Region"
}

variable "product_alias" {
  type        = string
  description = "Prod alias"
}

variable "env_alias" {
  type        = string
  description = "Environment alias"
}

variable "module_name" {
  type        = string
  description = "module name"
}

variable "component" {
  type        = string
  description = "Lambda/Layer/API"
}

variable "is_production" {
  description = "Is production"
  type        = bool
  default     = false
}

data "aws_caller_identity" "current" {}

data "aws_ecr_authorization_token" "token" {}

data "aws_region" "current" {}
