data "aws_vpc" "provided" {
  count = var.vpc_id != null ? 1 : 0
  id    = var.vpc_id
}

locals {
  vpc_id     = var.vpc_id != null ? var.vpc_id : module.vpc[0].vpc_id
  vpc_cidr   = var.vpc_id != null ? data.aws_vpc.provided[0].cidr_block : var.vpc_cidr
  subnet_ids = var.vpc_id != null ? var.private_subnet_ids : module.vpc[0].private_subnet_ids
  redis_host = var.redis_host != null ? var.redis_host : module.redis[0].endpoint
  redis_port = var.redis_host != null ? var.redis_port : module.redis[0].port
}

module "vpc" {
  source               = "app.terraform.io/yaalalabs/ak-vpc/aws"
  version              = "0.1.0-a1"
  count                = var.vpc_id == null ? 1 : 0
  vpc_cidr             = var.vpc_cidr
  public_subnet_cidrs  = var.public_subnet_cidrs
  private_subnet_cidrs = var.private_subnet_cidrs
  product_alias        = var.product_alias
  env_alias            = var.env_alias
  tags                 = var.tags
}

module "redis" {
  source        = "../modules/redis"
  count         = var.redis_host == null ? 1 : 0
  env_alias     = var.env_alias
  module_name   = var.module_name
  product_alias = var.product_alias
  vpc_cidr      = var.vpc_cidr
  vpc_id        = var.vpc_id
  subnet_ids    = var.private_subnet_ids
}

module "docker_image" {
  count         = 1
  source        = "app.terraform.io/yaalalabs/ak-lambda-docker/aws"
  version       = "0.1.0-a1"
  env_alias     = var.env_alias
  module_name   = var.module_name
  product_alias = var.product_alias
  source_path   = var.package_path
}
