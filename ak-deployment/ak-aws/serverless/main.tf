provider "aws" {
  region = var.region
}

terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "6.7.0" # pin terraform provider version
    }

  }
  required_version = ">= 1.9.5" # pin terraform version
}
