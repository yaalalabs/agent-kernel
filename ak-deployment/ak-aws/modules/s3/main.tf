resource "aws_s3_bucket" "source-storage" {
  bucket        = "${var.product_alias}-${var.env_alias}-sources-${data.aws_caller_identity.current.account_id}"
  force_destroy = true

  tags = merge({
    Name              = "${var.product_alias}-${var.env_alias}-sources-${data.aws_caller_identity.current.account_id}"
    Region            = var.region
    isS3BackupEnabled = var.is_production ? "true" : "false"
    backupType        = "critical"
    ResourceName      = "AppSourceBucket"
  }, var.s3_bucket_tags)
}

resource "aws_s3_bucket_policy" "source-storage-policy" {

  bucket = aws_s3_bucket.source-storage.id
  policy = data.aws_iam_policy_document.source-storage-policy-document.json

}

resource "aws_s3_bucket_public_access_block" "source-storage-block-public-access" {
  bucket                  = aws_s3_bucket.source-storage.id
  ignore_public_acls      = true
  restrict_public_buckets = true
  block_public_acls       = true
  block_public_policy     = true
}

resource "aws_s3_bucket_versioning" "source-storage-versioning" {

  bucket = aws_s3_bucket.source-storage.id
  versioning_configuration {
    status = var.is_production ? "Enabled" : "Disabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "source-storage-sse" {
  count = var.is_production ? 1 : 0

  bucket = aws_s3_bucket.source-storage.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = var.s3_kms_key_id
    }
  }
}