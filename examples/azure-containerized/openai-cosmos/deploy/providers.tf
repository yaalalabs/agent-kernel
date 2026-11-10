provider "azurerm" {
  features {
    persist_id_on_create_before_polling_for_completion = true
  }
  resource_provider_registrations = "none"
  resource_providers_to_register = [
    "Microsoft.ApiManagement",
    "Microsoft.App",
    "Microsoft.Cache",
    "Microsoft.ContainerRegistry",
    "Microsoft.DocumentDB",
    "Microsoft.Insights",
    "Microsoft.Network",
    "Microsoft.OperationalInsights",
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
