data "azurerm_subscription" "current" {}

variable "prefix" {
  type        = string
  description = "Prefix applied to every resource name (e.g. \"myproduct-dev-agents\")"
}

variable "region" {
  description = "Azure region (e.g., eastus, westus2)"
  type        = string
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
