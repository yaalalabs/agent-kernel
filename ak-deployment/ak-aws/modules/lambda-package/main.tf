locals {
  source_code_s3    = "${var.product_alias}-${var.env_alias}-source-storage-${data.aws_caller_identity.current.account_id}-${var.region}"
  package_type      = var.is_layer ? "layer" : "lambda"
  package_file_name = "source_code.zip"
  file_exist = fileexists(var.package_dir_path)
}

data "aws_s3_object" "source_code_object" {
  count  = local.file_exist ? 0 : 1
  bucket = local.source_code_s3
  key    = "${var.product_alias}/${var.region}/${var.env_alias}/${var.module_name}/${local.package_type}/${local.package_file_name}"
}
resource "aws_s3_object" "source_code" {
  bucket        = local.source_code_s3
  key           = "${var.product_alias}/${var.region}/${var.env_alias}/${var.module_name}/${local.package_type}/${local.package_file_name}"
  source        = local.file_exist ? var.package_dir_path : local.package_file_name
  etag          = local.file_exist ? filemd5(var.package_dir_path) : data.aws_s3_object.source_code_object[0].etag
  force_destroy = false
}