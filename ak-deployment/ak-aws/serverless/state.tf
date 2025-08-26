data "aws_vpc" "provided" {
  count = var.vpc_id != null ? 1 : 0
  id    = var.vpc_id
}

locals {
  lambda_kms_key_arn         = null
  cloudwatch_kms_key_arn     = null
  lambda_signer_profile_name = "sample_profile"
  lambda_signing_config_arn  = null
  vpc_id                     = var.vpc_id != null ? var.vpc_id : module.vpc[0].vpc_id
  vpc_cidr                   = var.vpc_id != null ? data.aws_vpc.provided[0].cidr_block : var.vpc_cidr
  subnet_ids                 = var.vpc_id != null ? var.private_subnet_ids : module.vpc[0].private_subnet_ids
  redis_host                 = var.redis_host != null ? var.redis_host : aws_elasticache_cluster.redis[0].cache_nodes[0].address
  redis_port                 = var.redis_host != null ? var.redis_port : aws_elasticache_cluster.redis[0].cache_nodes[0].port
}