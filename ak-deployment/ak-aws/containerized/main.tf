terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 6.11.0"
    }
    docker = {
      source  = "kreuzwerker/docker"
      version = "3.6.2"
    }
  }
  required_version = ">= 1.9.5"
}
