terraform {
  required_version = ">= 1.9.5"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = ">= 4.57.0"
    }
    docker = {
      source  = "kreuzwerker/docker"
      version = "3.6.2"
    }
  }
}

provider "azurerm" {
  features {}
  resource_provider_registrations = "none"
}

provider "docker" {
  registry_auth {
    address  = try(module.docker_image.login_server, null)
    username = try(module.docker_image.admin_username, null)
    password = try(module.docker_image.admin_password, null)
  }
}
