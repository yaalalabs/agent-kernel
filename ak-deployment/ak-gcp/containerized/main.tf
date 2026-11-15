terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "8.8.1"
    }
    google-beta = {
      source  = "hashicorp/google-beta"
      version = "8.8.1"
    }
    docker = {
      source  = "kreuzwerker/docker"
      version = "3.6.2"
    }
    null = {
      source  = "hashicorp/null"
      version = "3.2.4"
    }
    random = {
      source  = "hashicorp/random"
      version = "3.9.1"
    }
    time = {
      source  = "hashicorp/time"
      version = "0.14.2"
    }
  }
  required_version = ">= 1.9.5, <= 1.16.7"
}
