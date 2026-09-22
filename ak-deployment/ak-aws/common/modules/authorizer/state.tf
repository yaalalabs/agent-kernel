module "authorizer_source_storage" {
  count                = (var.authorizer_info.package_type == "S3Zip") ? 1 : 0
  source               = "yaalalabs/ak-common/aws//modules/s3"
  version              = "0.9.2"
  region               = var.region
  prefix               = var.prefix
  is_production        = var.is_production
  product_display_name = "Authorizer Lambda Storage"
  s3_kms_key_id        = ""
}

module "authorizer_source_package" {
  count            = (var.authorizer_info.package_type == "S3Zip") ? 1 : 0
  source           = "yaalalabs/ak-common/aws//modules/lambda-package"
  version          = "0.9.2"
  prefix           = "${var.prefix}-${var.authorizer_info.function_name}"
  region           = var.region
  package_dir_path = var.authorizer_info.package_path
  s3_bucket        = module.authorizer_source_storage[0].source_storage_s3_bucket
  depends_on = [module.authorizer_source_storage]
}

module "authorizer_docker_image" {
  count         = (var.authorizer_info.package_type == "Image") ? 1 : 0
  source        = "yaalalabs/ak-common/aws//modules/ecr"
  version       = "0.9.2"
  prefix        = "${var.prefix}-${var.authorizer_info.function_name}"
  source_path   = var.authorizer_info.package_path
}