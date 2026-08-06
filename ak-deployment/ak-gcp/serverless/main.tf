terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 6.8.0"
    }
    google-beta = {
      source  = "hashicorp/google-beta"
      version = ">= 6.8.0"
    }
    docker = {
      source  = "kreuzwerker/docker"
      version = "3.6.2"
    }
  }
  required_version = ">= 1.9.5"
}
