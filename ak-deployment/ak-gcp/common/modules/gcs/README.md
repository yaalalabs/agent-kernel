# GCS Module

A Terraform module for creating secure Google Cloud Storage buckets with versioning, encryption, and uniform access control.

## Overview

This module provisions a GCS bucket following GCP best practices:

- **Uniform Access**: IAM-only access control (no per-object ACLs)
- **Versioning**: Automatic versioning for production deployments
- **CMEK Support**: Optional customer-managed encryption keys
- **Force Destroy**: Configurable for easy cleanup in dev environments
- **Global Uniqueness**: Bucket name includes project ID for uniqueness

Perfect for storing Cloud Function source code (zip deployments), application data, logs, and any content requiring secure object storage.

## Requirements

| Name | Version |
|------|---------|
| Terraform | >= 1.9.5 |
| Google Provider | >= 6.8.0 |

## Usage

### Basic Example

```hcl
module "storage" {
  source = "../common/modules/gcs"
  # source = "yaalalabs/ak-common/google//modules/gcs"  # uncomment for registry

  project_id    = "my-gcp-project"
  region        = "us-central1"
  product_alias = "myapp"
  env_alias     = "prod"
  is_production = false
}
```

### Production with KMS Encryption

```hcl
resource "google_kms_crypto_key" "bucket_key" {
  name     = "myapp-bucket-key"
  key_ring = google_kms_key_ring.main.id
}

module "storage" {
  source = "../common/modules/gcs"
  # source = "yaalalabs/ak-common/google//modules/gcs"  # uncomment for registry

  project_id    = var.project_id
  region        = var.region
  product_alias = var.product_alias
  env_alias     = "prod"
  is_production = true
  kms_key_id    = google_kms_crypto_key.bucket_key.id

  labels = {
    environment = "production"
    compliance  = "soc2"
  }
}
```

### For Cloud Function Source Code

```hcl
module "source_storage" {
  source = "../common/modules/gcs"
  # source = "yaalalabs/ak-common/google//modules/gcs"  # uncomment for registry

  project_id    = var.project_id
  region        = var.region
  product_alias = var.product_alias
  env_alias     = var.env_alias
  is_production = var.is_production
}

# Upload function source code
resource "google_storage_bucket_object" "function_source" {
  name   = "functions/my-function/source.zip"
  bucket = module.source_storage.bucket_name
  source = "${path.module}/dist/function.zip"
}
```

## Inputs

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|:--------:|
| `project_id` | GCP project ID | `string` | n/a | yes |
| `region` | GCP region | `string` | `"us-central1"` | no |
| `product_alias` | Short identifier for the product | `string` | n/a | yes |
| `env_alias` | Environment identifier | `string` | n/a | yes |
| `is_production` | Enable production features (versioning) | `bool` | `false` | no |
| `kms_key_id` | KMS key ID for encryption (null = Google managed) | `string` | `null` | no |
| `labels` | Resource labels | `map(string)` | `{}` | no |

## Outputs

| Name | Description | Example |
|------|-------------|---------|
| `bucket_name` | GCS bucket name | `myapp-prod-sources-my-gcp-project` |
| `bucket_url` | GCS bucket URL | `gs://myapp-prod-sources-my-gcp-project` |
| `bucket_self_link` | Bucket self link | `https://www.googleapis.com/storage/v1/b/myapp-prod-sources-my-gcp-project` |

## Features

### Naming Convention

Bucket name: `{product_alias}-{env_alias}-sources-{project_id}`

The project ID is included to ensure global uniqueness (GCS bucket names must be unique across all of Google Cloud).

### Uniform Bucket-Level Access

All access is controlled via IAM. No per-object ACLs. This is simpler and more secure than mixed ACL/IAM access.

### Versioning

- **Production** (`is_production = true`): Versioning enabled. Old versions kept for recovery
- **Development** (`is_production = false`): Versioning disabled. Saves storage costs

### Force Destroy

`force_destroy = true` is enabled so Terraform can delete the bucket even when it contains objects. This makes cleanup easy in dev environments. Versioning protects production data.

### CMEK Encryption

By default, Google manages the encryption key. For compliance requirements, you can provide your own KMS key via `kms_key_id`.

## GCP vs AWS Comparison

| GCP (GCS) | AWS (S3) |
|-----------|----------|
| `google_storage_bucket` (1 resource) | `aws_s3_bucket` + `aws_s3_bucket_policy` + `aws_s3_bucket_versioning` + `aws_s3_bucket_encryption` (4+ resources) |
| Uniform bucket access (built-in) | Block public access (separate resource) |
| Labels | Tags |
| CMEK via `encryption` block | SSE-KMS via separate config |
| Regional / Multi-regional | Regional / Cross-region replication |

**Key difference**: GCS is 1 resource with everything built in. S3 needs 4+ separate resources for the same configuration.

## Cost Considerations

| Storage Class | Cost/GB/month | Use Case |
|---------------|--------------|----------|
| Standard | $0.020 | Frequently accessed |
| Nearline | $0.010 | Monthly access |
| Coldline | $0.004 | Quarterly access |
| Archive | $0.0012 | Yearly access |

This module uses Standard storage class by default.

**Cost Tips**:
1. Use lifecycle rules to move old objects to cheaper storage classes
2. Disable versioning in dev environments
3. Clean up old function source zips periodically

## Related Modules

- [VPC Module](../vpc/) - Network infrastructure
- [Artifact Registry Module](../artifact-registry/) - For Docker images (alternative to zip)
- [Firestore Module](../firestore/) - Document database

---

**Note**: GCS bucket names are globally unique across all of Google Cloud. The module includes the project ID in the name to avoid conflicts.
