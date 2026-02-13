variable "product_alias" {
  type        = string
  description = "The product alias (used in ACR name and image name)"
}

variable "env_alias" {
  type        = string
  description = "The environment alias (dev, staging, d, etc.)"
}

variable "module_name" {
  type        = string
  description = "The module name (part of ACR and image name)"
}

variable "region" {
  type        = string
  description = "The Azure region to deploy to"
}

variable "resource_group_name" {
  type        = string
  description = "The Azure resource group to deploy to"
}

variable "product_display_name" {
  type        = string
  description = "The product display name"
  default     = "Demo Platform API"
}

variable "publisher_email" {
  type        = string
  description = "The publisher email"
}

variable "environment_variables" {
  type        = map(string)
  description = "The environment variables to pass to the container"
  default     = {}
}

variable "openai_api_key" {
  type        = string
  description = "The OpenAI API key"
}