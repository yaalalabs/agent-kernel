data "azurerm_subscription" "current" {}

variable "product_alias" {
  type        = string
  description = "Product alias"
}

variable "region" {
  description = "Azure region (e.g., eastus, westus2)"
  type        = string
}

variable "env_alias" {
  type        = string
  description = "Environment alias"
}

variable "product_display_name" {
  type        = string
  description = "Product display name"
}

variable "resource_group_name" {
  type        = string
  description = "Name of the Azure resource group"
}

variable "blob_tags" {
  description = "A map of tags to add"
  type        = map(string)
  default     = {}
}

variable "blob_kms_key_id" {
  type        = string
  default     = null
  description = "Full Azure Key Vault Key ID (format: https://vault-name.vault.azure.net/keys/key-name/version)"
}

variable "is_production" {
  type        = bool
  description = "Whether this is a production environment"
}
