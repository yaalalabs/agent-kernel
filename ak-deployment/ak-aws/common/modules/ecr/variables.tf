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
  default     = null
}

variable "is_production" {
  description = "Is production"
  type        = bool
  default     = false
}

variable "module_name" {
  type        = string
  description = "module name"
}

variable "source_path" {
  type        = string
  description = "Source path"
}