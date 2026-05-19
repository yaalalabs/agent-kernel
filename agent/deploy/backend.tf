# OPTIONAL: This file is auto-generated for CI/CD purposes
# You can safely delete this file if you prefer to use local state
# or configure your own backend

terraform {
  backend "s3" {
    bucket         = "agent-kernel-terraform-state-bucket-dev"
    key            = "ak-agent/public/terraform.tfstate"
    region         = "ap-southeast-2"
    use_lockfile   = true
    encrypt        = true
  }
}
