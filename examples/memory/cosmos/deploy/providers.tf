provider "azurerm" {
  features {}
  resource_provider_registrations = "none"
  resource_providers_to_register = [
    "Microsoft.ApiManagement",
    "Microsoft.Cache",
    "Microsoft.DocumentDB",
    "Microsoft.Insights",
    "Microsoft.Network",
    "Microsoft.Storage",
    "Microsoft.Web",
  ]
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
