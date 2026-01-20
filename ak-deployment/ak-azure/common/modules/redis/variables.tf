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

# Azure Redis SKU mapping
variable "sku_name" {
  type        = string
  description = "Redis SKU name (Basic, Standard, or Premium)"
  default     = "Premium"
  
  validation {
    condition     = contains(["Basic", "Standard", "Premium"], var.sku_name)
    error_message = "SKU must be Basic, Standard, or Premium"
  }
}

variable "node_family" {
  type        = string
  description = "Redis family (C for Basic/Standard, P for Premium)"
  default     = "P"
  
  validation {
    condition     = contains(["C", "P"], var.node_family)
    error_message = "Family must be C (Basic/Standard) or P (Premium)"
  }
}

variable "node_capacity" {
  type        = number
  description = "Redis capacity (0-6 for C family, 1-5 for P family)"
  default     = 1
  
  validation {
    condition     = var.node_capacity >= 0 && var.node_capacity <= 6
    error_message = "Capacity must be between 0 and 6"
  }
}

variable "port" {
  type        = number
  description = "Redis port "
  default     = 6379
}