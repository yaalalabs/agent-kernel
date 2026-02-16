variable "resource_group_name" {
  type        = string
  description = "Resource group name"
}

variable "product_alias" {
  type        = string
  description = "Product alias"
}

variable "env_alias" {
  type        = string
  description = "Environment alias"
}

variable "module_name" {
  type        = string
  description = "Module name"
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