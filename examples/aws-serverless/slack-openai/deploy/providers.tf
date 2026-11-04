provider "aws" {
  region = var.region
}

# The agent runner deploys as a container image (package_type = "Image"), so the module needs a
# configured docker provider to build the image and push it to the ECR repository it creates. The
# request and response handlers still deploy as local zips.

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
      source = "hashicorp/aws"
      # Pinned to 6.70.0: 6.69.0 fails to create a zip-packaged Lambda with "decomposing request: bufio.Scanner: token
      # too long" (https://github.com/hashicorp/terraform-provider-aws/issues/50474); fixed in 6.69.1.
      version = "6.70.0"
    }
    docker = {
      source  = "kreuzwerker/docker"
      version = "3.6.2"
    }
  }
}
