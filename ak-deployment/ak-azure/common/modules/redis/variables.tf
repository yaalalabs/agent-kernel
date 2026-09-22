variable "resource_group_name" {
  type        = string
  description = "Resource group name"
}

variable "region" {
  type        = string
  description = "Azure region for resources"
}

variable "prefix" {
  type        = string
  description = "Prefix applied to every resource name (e.g. \"myproduct-dev-agents\")"
}

variable "tags" {
  type        = map(string)
  description = "Resource tags"
  default     = {}
}

variable "vnet_name" {
  type        = string
  description = "Virtual Network name"
}

variable "vnet_resource_group_name" {
  type        = string
  description = "VNet resource group name (if different from current RG)"
  default     = null
}

variable "subnet_name" {
  type        = string
  description = "Subnet name for private endpoint"
}

variable "function_subnet" {
  type        = string
  description = "Subnet name for private endpoint"
}

variable "is_production" {
  type = bool
  description = "Is production?"
  default = false
}

variable "create_NSG" {
  type = bool
  description = "Create NSG? this may be handled from else where"
  default = false
}