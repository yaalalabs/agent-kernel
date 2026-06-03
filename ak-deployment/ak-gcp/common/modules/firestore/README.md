# Firestore Module

A Terraform module for creating Google Firestore databases in Native mode with TTL policies and composite indexes for session storage.

## Overview

This module provisions a Firestore database optimized for agent session storage:

- **Firestore Native**: Modern document database (GCP's equivalent of DynamoDB)
- **TTL Policy**: Automatic deletion of expired session records
- **Composite Index**: Pre-configured index for fast session lookups by session_id + key
- **Deletion Protection**: Optional protection against accidental deletion
- **Point-in-Time Recovery**: Optional backup and recovery support

Perfect for agent session storage, document data, key-value storage, and any workload needing a managed NoSQL database.

## Requirements

| Name | Version |
|------|---------|
| Terraform | >= 1.9.5 |
| Google Provider | >= 6.8.0 |

## Usage

### Basic Example

```hcl
module "firestore" {
  source = "../common/modules/firestore"
  # source = "yaalalabs/ak-common/google//modules/firestore"  # uncomment for registry

  project_id    = "my-gcp-project"
  region        = "us-central1"
  product_alias = "myapp"
  env_alias     = "prod"
  module_name   = "chatbot"
}
```

### Production Setup

```hcl
module "firestore" {
  source = "../common/modules/firestore"
  # source = "yaalalabs/ak-common/google//modules/firestore"  # uncomment for registry

  project_id    = var.project_id
  region        = var.region
  product_alias = var.product_alias
  env_alias     = "prod"
  module_name   = var.module_name

  collection_name        = "sessions"
  ttl_field              = "expiry_time"
  deletion_protection    = true
  point_in_time_recovery = true
}
```

### With Cloud Run

```hcl
module "firestore" {
  source = "../common/modules/firestore"

  project_id    = var.project_id
  region        = var.region
  product_alias = var.product_alias
  env_alias     = var.env_alias
  module_name   = var.module_name
}

# Cloud Run uses Firestore via environment variables
# AK_SESSION__FIRESTORE__DATABASE = module.firestore.database_name
# AK_SESSION__FIRESTORE__PROJECT  = var.project_id
```

## Inputs

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|:--------:|
| `project_id` | GCP project ID | `string` | n/a | yes |
| `region` | GCP region | `string` | `"us-central1"` | no |
| `product_alias` | Short identifier for the product | `string` | n/a | yes |
| `env_alias` | Environment identifier | `string` | n/a | yes |
| `module_name` | Module name for resource identification | `string` | n/a | yes |
| `collection_name` | Firestore collection name | `string` | `"sessions"` | no |
| `ttl_field` | Field name for TTL expiration | `string` | `"expiry_time"` | no |
| `deletion_protection` | Enable deletion protection | `bool` | `false` | no |
| `point_in_time_recovery` | Enable point-in-time recovery | `bool` | `false` | no |

## Outputs

| Name | Description | Example |
|------|-------------|---------|
| `database_name` | Firestore database name | `myapp-prod-chatbot` |
| `database_id` | Firestore database ID | `myapp-prod-chatbot` |
| `collection_name` | Collection name | `sessions` |
| `project_id` | GCP project ID | `my-gcp-project` |

## Features

### Named Databases

Firestore supports multiple named databases per project. This module creates a named database (not the default `(default)` database), so you can have separate databases for different services.

Database ID format: `{product_alias}-{env_alias}-{module_name}`

### TTL Policy

The TTL policy automatically deletes documents when their `expiry_time` field passes. This keeps your database clean without any manual cleanup code.

```python
# In your app, set expiry_time when creating a session
from datetime import datetime, timedelta

doc = {
    "session_id": "abc123",
    "key": "chat_history",
    "data": {...},
    "expiry_time": datetime.now() + timedelta(hours=24)  # auto-delete after 24h
}
```

### Composite Index

Pre-configured index on `session_id` (ascending) + `key` (ascending). This matches the DynamoDB pattern of partition key + sort key, giving you fast lookups for:

```python
# Fast query: get all data for a session
db.collection("sessions").where("session_id", "==", "abc123").get()

# Fast query: get specific key for a session
db.collection("sessions") \
    .where("session_id", "==", "abc123") \
    .where("key", "==", "chat_history") \
    .get()
```

## GCP vs AWS Comparison

| GCP (Firestore) | AWS (DynamoDB) |
|------------------|----------------|
| `google_firestore_database` | `aws_dynamodb_table` |
| `google_firestore_field` (TTL) | TTL config in table resource |
| `google_firestore_index` | GSI/LSI in table resource |
| Native document model | Key-value with document support |
| Named databases per project | One table per resource |
| No capacity planning (Native mode) | On-demand or provisioned |

**Key difference**: Firestore Native mode has no capacity planning. You just use it and pay per operation. DynamoDB on-demand is similar but Firestore has a simpler pricing model.

## Cost Considerations

| Operation | Cost |
|-----------|------|
| Document reads | $0.06 per 100K |
| Document writes | $0.18 per 100K |
| Document deletes | $0.02 per 100K |
| Storage | $0.18/GB per month |

**Free tier**: 50K reads, 20K writes, 20K deletes per day. Good enough for development.

**Cost Tips**:
1. Use TTL to auto-delete old sessions (reduces storage)
2. Use composite indexes to avoid full collection scans
3. Batch reads/writes when possible

## Troubleshooting

### Permission Denied

Ensure the service account has `roles/datastore.user`:
```bash
gcloud projects add-iam-policy-binding my-project \
  --member="serviceAccount:my-sa@my-project.iam.gserviceaccount.com" \
  --role="roles/datastore.user"
```

### Database Already Exists

Firestore database names are unique per project. If you get a conflict, the database already exists. Either import it into Terraform state or use a different `module_name`.

### TTL Not Working

TTL deletions can take up to 24 hours after the expiry time. This is by design - Firestore processes TTL deletions in the background.

## Related Modules

- [VPC Module](../vpc/) - Network infrastructure
- [Memorystore Module](../memorystore/) - Alternative: Redis for caching
- [GCS Module](../gcs/) - Object storage

---

**Note**: Firestore requires the Firestore API to be enabled in your GCP project. Run `gcloud services enable firestore.googleapis.com` before deploying.
