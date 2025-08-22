locals {
  lambda_kms_key_arn         = null
  cloudwatch_kms_key_arn     = null
  lambda_signer_profile_name = "sample_profile"
  lambda_signing_config_arn  = null
  vpc_id                     = module.vpc.vpc_id
  subnet_ids                 = module.vpc.private_subnet_ids
}