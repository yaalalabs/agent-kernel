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
  redis_url                  = var.create_redis_cluster == true ? module.redis[0].url : null
  dynamodb_memory_table_arn  = var.create_dynamodb_memory_table == true ? module.dynamodb_memory[0].table_arn : null
  dynamodb_memory_table_name = var.create_dynamodb_memory_table == true ? module.dynamodb_memory[0].table_name : null

  all_endpoints = merge(
    {
      default = {
        path   = var.agent_endpoint
        method = "POST"
      }
    },
    {
      for ep in var.gateway_endpoints :
      ep.path => ep
    }
  )  
}

module "vpc" {
  source               = "yaalalabs/ak-common/aws//modules/vpc"
  version              = "0.2.9"
  count                = var.vpc_id == null ? 1 : 0
  vpc_cidr             = var.vpc_cidr
  public_subnet_cidrs  = var.public_subnet_cidrs
  private_subnet_cidrs = var.private_subnet_cidrs
  product_alias        = var.product_alias
  env_alias            = var.env_alias
  tags                 = var.tags
}


module source_storage {
  count                = (var.package_type == "S3Zip") ? 1 : 0
  source               = "yaalalabs/ak-common/aws//modules/s3"
  version              = "0.2.9"
  region               = var.region
  env_alias            = var.env_alias
  is_production        = var.is_production
  product_alias        = var.product_alias
  product_display_name = var.product_display_name
  s3_kms_key_id        = ""
}

module source_package {
  count            = (var.package_type == "S3Zip") ? 1 : 0
  source           = "yaalalabs/ak-common/aws//modules/lambda-package"
  version          = "0.2.9"
  env_alias        = var.env_alias
  module_name      = var.module_name
  package_dir_path = var.package_path
  product_alias    = var.product_alias
  s3_bucket        = module.source_storage[0].source_storage_s3_bucket
  depends_on = [module.source_storage]
}

module docker_image {
  count         = (var.package_type == "Image") ? 1 : 0
  source        = "yaalalabs/ak-common/aws//modules/ecr"
  version       = "0.2.9"
  env_alias     = var.env_alias
  module_name   = var.module_name
  product_alias = var.product_alias
  source_path   = var.package_path
}

module "redis" {
  source        = "yaalalabs/ak-common/aws//modules/redis"
  version       = "0.2.9"
  count         = var.create_redis_cluster == true ? 1 : 0
  env_alias     = var.env_alias
  module_name   = var.module_name
  product_alias = var.product_alias
  vpc_cidr      = local.vpc_cidr
  vpc_id        = local.vpc_id
  subnet_ids    = local.subnet_ids
}

module dynamodb_memory {
  source  = "yaalalabs/ak-common/aws//modules/dynamodb"
  version = "0.2.9"
  count   = var.create_dynamodb_memory_table == true ? 1 : 0
  attributes = [
    { name = "session_id", type = "S" },
    { name = "key", type = "S" },
  ]
  hash_key           = "session_id"
  range_key          = "key"
  ttl_enabled        = true
  env_alias          = var.env_alias
  module_name        = var.module_name
  product_alias      = var.product_alias
  table_name         = "session_store"
  ttl_attribute_name = "expiry_time"
}