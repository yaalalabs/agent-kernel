provider "aws" {
  region = var.region
}

terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "6.7.0" # pin terraform provider version
    }
    docker = {
      source  = "kreuzwerker/docker"
      version = "3.6.0"
    }
  }
  required_version = ">= 1.9.5" # pin terraform version
}

provider "docker" {
  registry_auth {
    address = format("%v.dkr.ecr.%v.amazonaws.com", data.aws_caller_identity.current.account_id, var.region)
    username = data.aws_ecr_authorization_token.token.user_name
    password = data.aws_ecr_authorization_token.token.password
  }
}