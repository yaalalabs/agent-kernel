provider "azurerm" {
  features {
    persist_id_on_create_before_polling_for_completion = true
  }
  resource_provider_registrations = "none"
}

terraform {
  required_version = ">= 1.9.5"
  required_providers {
    azurerm = {
      source = "hashicorp/azurerm"
      # 4.75.0 is the first release with persist_id_on_create_before_polling_for_completion
      version = ">= 4.75.0, < 5.0.0"
    }
  }
}
