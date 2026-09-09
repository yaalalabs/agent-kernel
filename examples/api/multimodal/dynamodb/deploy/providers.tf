provider "aws" {
  region = var.region
}

data "aws_caller_identity" "current" {}
data "aws_ecr_authorization_token" "token" {}

provider "docker" {
  registry_auth {
    address  = format("%v.dkr.ecr.%v.amazonaws.com", data.aws_caller_identity.current.account_id, var.region)
    username = data.aws_ecr_authorization_token.token.user_name
    password = data.aws_ecr_authorization_token.token.password
  }
}

terraform {
  required_version = ">= 1.9.5"
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
}
