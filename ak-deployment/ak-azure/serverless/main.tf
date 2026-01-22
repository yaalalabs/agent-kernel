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

    null = {
      source  = "hashicorp/null"
      version = "3.2.4"
    }

    time = {
      source  = "hashicorp/time"
      version = ">= 0.9.0"
    }
  }
}

provider "azurerm" {
  features {}
  subscription_id = "c9241329-6b5e-4c4d-a88d-1a2cefa724d6"
  resource_provider_registrations = "none"
}

provider "docker" {
  registry_auth {
    address  = try(module.docker_image[0].login_server, null)
    username = try(module.docker_image[0].admin_username, null)
    password = try(module.docker_image[0].admin_password, null)
  }
}
