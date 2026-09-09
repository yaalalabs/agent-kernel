# Artifact Registry Module

A Terraform module for building Docker container images and storing them in Google Artifact Registry for Cloud Functions and Cloud Run deployments.

## Overview

This module automates the complete Docker image lifecycle:

- **Artifact Registry**: Creates and manages Docker repositories with cleanup policies
- **Docker Build**: Builds images from source code with automatic platform targeting
- **Content-Hash Rebuild**: Tracks source file changes to trigger rebuilds only when code changes
- **Auto Push**: Pushes built images to Artifact Registry automatically
- **Lifecycle Policies**: Keeps last 30 images, auto-deletes older ones

Perfect for serverless Cloud Functions, Cloud Run services, and any containerized workload on GCP.

## Requirements

| Name | Version |
|------|---------|
| Terraform | >= 1.9.5 |
| Google Provider | >= 6.8.0 |
| Docker Provider | >= 3.6.2 |

## Usage

### Basic Example

```hcl
module "docker_image" {
  source = "../common/modules/artifact-registry"
  # source = "yaalalabs/ak-common/google//modules/artifact-registry"  # uncomment for registry

  project_id    = "my-gcp-project"
  region        = "us-central1"
  product_alias = "myapp"
  env_alias     = "prod"
  module_name   = "api"
  source_path   = "${path.module}/src"
}

# Use the image in Cloud Run
resource "google_cloud_run_v2_service" "service" {
  name     = "my-service"
  location = "us-central1"

  template {
    containers {
      image = module.docker_image.image_url
    }
  }
}
```

### With Cloud Functions v2

```hcl
module "docker_image" {
  source = "../common/modules/artifact-registry"
  # source = "yaalalabs/ak-common/google//modules/artifact-registry"  # uncomment for registry

  project_id    = var.project_id
  region        = var.region
  product_alias = var.product_alias
  env_alias     = var.env_alias
  module_name   = var.module_name
  source_path   = var.package_path
}

resource "google_cloudfunctions2_function" "function" {
  name     = "my-function"
  location = var.region

  build_config {
    docker_repository = "projects/${var.project_id}/locations/${var.region}/repositories/${module.docker_image.repository_id}"
  }
}
```

## Inputs

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|:--------:|
| `project_id` | GCP project ID | `string` | n/a | yes |
| `region` | GCP region | `string` | `"us-central1"` | no |
| `product_alias` | Short identifier for the product | `string` | n/a | yes |
| `env_alias` | Environment identifier | `string` | n/a | yes |
| `module_name` | Module name for resource identification | `string` | n/a | yes |
| `source_path` | Path to directory containing Dockerfile and source code | `string` | n/a | yes |

## Outputs

| Name | Description | Example |
|------|-------------|---------|
| `image_url` | Complete image URI for deployment | `us-central1-docker.pkg.dev/my-project/myapp-prod-api/api:abc123` |
| `repository_id` | Artifact Registry repository ID | `myapp-prod-api` |
| `repository_url` | Artifact Registry repository URL | `us-central1-docker.pkg.dev/my-project/myapp-prod-api` |

## Features

### Content-Hash Rebuild (dir_sha)

The module calculates a SHA1 hash of all source files (excluding `__pycache__`). This means:

- **No code changes = no rebuild**. Terraform skips the Docker build entirely
- **Any file changes = automatic rebuild**. Even a one-line change triggers a new image
- The hash is used as the image tag, so each code version gets a unique tag

```hcl
# How it works internally:
dir_sha = sha1(join("", [for f in local.files : filesha1("${source_path}/${f}")]))
image_tag = local.dir_sha  # e.g., "a1b2c3d4e5f6..."
```

### Cleanup Policies

The repository keeps only the last 30 images. Older images are automatically deleted. This prevents storage costs from growing over time.

### Naming Convention

- Repository: `{product_alias}-{env_alias}-{module_name}`
- Image URL: `{region}-docker.pkg.dev/{project_id}/{repo_name}/{module_name}:{dir_sha}`

## Source Directory Structure

Your source directory needs a `Dockerfile`:

```
src/
  Dockerfile          # Required
  requirements.txt    # Python dependencies
  app/
    main.py
    utils.py
```

### Example Dockerfile

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

## GCP vs AWS Comparison

| GCP (Artifact Registry) | AWS (ECR) |
|--------------------------|-----------|
| `google_artifact_registry_repository` | `aws_ecr_repository` |
| `docker_image` + `docker_registry_image` | `docker_image` + `docker_registry_image` |
| Supports Docker, Maven, npm, Python | Docker only |
| Cleanup via `cleanup_policies` | Cleanup via `lifecycle_policy` |
| Regional by default | Regional by default |

## Cost Considerations

| Resource | Cost |
|----------|------|
| Storage | $0.10/GB per month |
| Network (same region) | Free |
| Network (cross region) | Standard egress rates |

**Tip**: The cleanup policy (keep last 30) prevents storage from growing unbounded.

## Related Modules

- [VPC Module](../vpc/) - Network for Cloud Run/Functions
- [Memorystore Module](../memorystore/) - Redis cache
- [Firestore Module](../firestore/) - Document database

---

**Note**: This module requires Docker to be installed and running on the machine where Terraform is executed. The Docker provider must be configured with Artifact Registry authentication.
