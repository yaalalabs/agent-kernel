terraform {
  required_version = ">= 1.9.5"
  required_providers {
    aws = {
      source = "hashicorp/aws"
      # Pinned to 6.70.0: 6.69.0 fails to create a zip-packaged Lambda with "decomposing request: bufio.Scanner: token
      # too long" (https://github.com/hashicorp/terraform-provider-aws/issues/50474); fixed in 6.69.1.
      version = "6.70.0"
    }
  }
}
