locals {
  lambda_kms_key_arn         = null
  cloudwatch_kms_key_arn     = null
  lambda_signer_profile_name = "sample_profile"
  lambda_signing_config_arn  = null
}

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

data "aws_security_group" "default" {
  vpc_id = data.aws_vpc.default.id
  name   = "default"
}