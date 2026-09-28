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

variable "source_path" {
  type        = string
  description = "Source path"
}