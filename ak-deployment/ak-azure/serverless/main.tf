terraform {
  required_version = ">= 1.9.5"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = ">= 4.57.0, < 5.0.0"
    }

    null = {
      source  = "hashicorp/null"
      version = "3.2.4"
    }

  }
}