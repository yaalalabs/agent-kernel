provider "azurerm" {
  features {
    persist_id_on_create_before_polling_for_completion = true
  }
  resource_provider_registrations = "none"
}

terraform {
  required_version = ">= 1.9.5, <= 1.16.7"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "5.11.0"
    }
  }
}
