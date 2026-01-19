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
  description = "Module name (logical component name)"
}

variable "tags" {
  type        = map(string)
  description = "Resource tags"
  default     = {}
}

variable "table_name" {
  type        = string
  description = "Table name (DynamoDB equivalent)"
}

variable "resource_group_name" {
  type        = string
  description = "Azure resource group name"
}

# Capacity & billing
variable "billing_mode" {
  type        = string
  description = "Billing mode: PROVISIONED or PAY_PER_REQUEST (serverless)"
  default     = "PAY_PER_REQUEST"
  validation {
    condition     = contains(["PROVISIONED", "PAY_PER_REQUEST"], var.billing_mode)
    error_message = "billing_mode must be either PROVISIONED or PAY_PER_REQUEST"
  }
}

variable "provisioned_throughput" {
  type        = number
  description = "Provisioned throughput (RU/s) when billing_mode is PROVISIONED"
  default     = 400
}

variable "autoscale_max_throughput" {
  type        = number
  description = "Maximum autoscale throughput (RU/s). If set, enables autoscale for PROVISIONED mode."
  default     = null
}

variable "read_capacity" {
  type        = number
  description = "Read capacity units (compatibility variable, not used in Azure)"
  default     = null
}

variable "write_capacity" {
  type        = number
  description = "Write capacity units (compatibility variable, not used in Azure)"
  default     = null
}

# Data protection
variable "point_in_time_recovery_enabled" {
  type        = bool
  description = "Enable continuous backup (Point-in-Time Recovery)"
  default     = false
}

variable "server_side_encryption_enabled" {
  type        = bool
  description = "Enable customer-managed encryption key (encryption is always on by default)"
  default     = false
}

variable "key_vault_key_id" {
  type        = string
  description = "Key Vault key ID for customer-managed encryption"
  default     = null
}

# Azure-specific Cosmos DB settings
variable "consistency_level" {
  type        = string
  description = "Consistency level: Strong, BoundedStaleness, Session, ConsistentPrefix, Eventual"
  default     = "Session"
  validation {
    condition     = contains(["Strong", "BoundedStaleness", "Session", "ConsistentPrefix", "Eventual"], var.consistency_level)
    error_message = "Invalid consistency level"
  }
}

variable "public_network_access_enabled" {
  type        = bool
  description = "Enable public network access"
  default     = true
}