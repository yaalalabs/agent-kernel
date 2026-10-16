terraform {
  required_providers {
    aws = {
      source = "hashicorp/aws"
      # Below 6.69.0: it fails to create a zip-packaged Lambda with "decomposing request: bufio.Scanner: token too
      # long" (https://github.com/hashicorp/terraform-provider-aws/issues/50474). Lift once a fixed release ships.
      version = ">= 6.11.0, < 6.69.0"
    }
    docker = {
      source  = "kreuzwerker/docker"
      version = "3.6.2"
    }
  }
  required_version = ">= 1.9.5" # pin terraform version
}