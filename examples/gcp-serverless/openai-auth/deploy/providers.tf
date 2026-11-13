provider "google" {
  project = var.project_id
  region  = var.region
}

provider "google-beta" {
  project = var.project_id
  region  = var.region
}

data "google_client_config" "current" {}

# Authenticate Docker to push images to Artifact Registry
provider "docker" {
  registry_auth {
    address  = "${var.region}-docker.pkg.dev"
    username = "oauth2accesstoken"
    password = data.google_client_config.current.access_token
  }
}

terraform {
  required_version = ">= 1.9.5, <= 1.16.7"
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
  }
}
