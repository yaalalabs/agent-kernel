variable "region" {
  type        = string
  description = "Region"
}

variable "prefix" {
  type        = string
  description = "Prefix applied to every resource name (e.g. \"myproduct-dev-agents\")"
}

variable "source_path" {
  type        = string
  description = "Source path"
}

variable "resource_group_name" {
  type        = string
  description = "Resource group name"
}

variable "enabled" {
  type        = bool
  description = "Enable the module"
  default     = true
}