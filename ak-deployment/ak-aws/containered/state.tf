data "aws_vpc" "provided" {
  count = var.vpc_id != null ? 1 : 0
  id    = var.vpc_id
}

locals {
  vpc_id     = var.vpc_id != null ? var.vpc_id : module.vpc[0].vpc_id
  vpc_cidr   = var.vpc_id != null ? data.aws_vpc.provided[0].cidr_block : var.vpc_cidr
  subnet_ids = var.vpc_id != null ? var.private_subnet_ids : module.vpc[0].private_subnet_ids
  redis_url  = var.create_redis_cluster == true ? module.redis[0].url : null
  prefix = "${var.product_alias}-${var.env_alias}-${var.module_name}"
  service_name = "${local.prefix}-service"
  container_name = "${local.prefix}-app"
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
  source        = "../common/redis"
  count         = var.create_redis_cluster == true ? 1 : 0
  env_alias     = var.env_alias
  module_name   = var.module_name
  product_alias = var.product_alias
  vpc_cidr      = local.vpc_cidr
  vpc_id        = local.vpc_id
  subnet_ids    = local.subnet_ids
}

module "docker_image" {
  count         = 1
  source = "../common/ecr"
  # version       = "0.1.0-a1"
  env_alias     = var.env_alias
  module_name   = var.module_name
  product_alias = var.product_alias
  source_path   = var.package_path
}
