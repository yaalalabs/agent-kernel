terraform {
  required_version = ">= 1.9.5"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 6.8.0"
    }
  }
}
