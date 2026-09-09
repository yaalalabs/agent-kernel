provider "azurerm" {
  features {}
  resource_provider_registrations = "none"
}

terraform {
  required_version = ">= 1.9.5"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = ">= 4.57.0, < 5.0.0"
    }
  }
}
