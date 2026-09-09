# Remote state so the GitHub Actions deploy workflow and local applies share one state.
# Same bucket/convention as agent/deploy/backend.tf and scripts/deploy/state-config.yaml.
terraform {
  backend "s3" {
    bucket       = "agent-kernel-terraform-state-bucket-dev"
    key          = "e2e/messaging/terraform.tfstate"
    region       = "ap-southeast-2"
    use_lockfile = true
    encrypt      = true
  }
}
