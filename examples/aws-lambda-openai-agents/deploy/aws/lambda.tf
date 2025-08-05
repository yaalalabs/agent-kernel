module "lambda_package" {
  count = (var.component == "lambda") ? 1 : 0

  source = "../../../../ak-deployment/ak/modules/lambda-package"

  package_dir_path = "dist.zip"
  region           = var.region
  env_alias        = var.env_alias
  module_name      = var.module_name
  product_alias    = var.product_alias
}