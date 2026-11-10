terraform {
  required_version = ">= 1.9.5, <= 1.16.7"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "8.8.1"
    }
  }
}
