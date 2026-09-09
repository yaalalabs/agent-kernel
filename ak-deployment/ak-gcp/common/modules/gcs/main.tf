# Build the bucket name from project ID to keep it globally unique
locals {
  bucket_name = "${var.product_alias}-${var.env_alias}-sources-${var.project_id}"
}

# The storage bucket — equivalent of S3 or Azure Blob Storage
resource "google_storage_bucket" "source_storage" {
  name     = local.bucket_name
  project  = var.project_id
  location = var.region

  # Prevent anyone from making objects public by accident
  uniform_bucket_level_access = true

  # Force destroy lets terraform delete the bucket even if it has objects
  # handy for dev environments, safe because versioning protects prod
  force_destroy = true

  # Turn on versioning in production so we can recover deleted files
  versioning {
    enabled = var.is_production
  }

  # Use CMEK if provided, otherwise Google manages the key
  dynamic "encryption" {
    for_each = var.kms_key_id != null ? [1] : []
    content {
      default_kms_key_name = var.kms_key_id
    }
  }

  labels = var.labels
}
