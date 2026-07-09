---
sidebar_position: 6
---

# GCP Serverless (Cloud Run)

Deploy Agent Kernel agents as serverless containers on **GCP Cloud Run** with scale-to-zero capability. Uses the [`yaalalabs/ak-serverless/google`](https://registry.terraform.io/modules/yaalalabs/ak-serverless/google) Terraform module.

## Overview

| Component | GCP Service |
|-----------|------------|
| Compute | Cloud Run (scale-to-zero, min_instance_count=0) |
| API Gateway | GCP API Gateway (OpenAPI-based) |
| Container Registry | Artifact Registry |
| Session Store (Redis) | Memorystore Redis |
| Session Store (Firestore) | Firestore (Native Mode) |
| Networking | VPC + VPC Access Connector + Cloud NAT |
| Observability | Cloud Logging (built-in) |

## Prerequisites

- GCP CLI configured: `gcloud auth application-default login`
- Terraform >= 1.9.5
- Docker installed
- An existing GCP project with billing enabled
- Required APIs enabled:
  - `run.googleapis.com`
  - `apigateway.googleapis.com`
  - `artifactregistry.googleapis.com`
  - `vpcaccess.googleapis.com`
  - `redis.googleapis.com` (if using Redis)
  - `firestore.googleapis.com` (if using Firestore)

## Agent Code

Use `agentkernel.gcp.CloudRun` as the entry point:

```python
from agentkernel.gcp import CloudRun
from agentkernel.openai import OpenAIModule

OpenAIModule([...])

@CloudRun.register("/app", method="GET")
def app_handler() -> dict:
    return {"status": "ok"}

def main() -> None:
    CloudRun.run()

if __name__ == "__main__":
    main()
```

## Dependencies

```toml
# pyproject.toml
dependencies = [
  "agentkernel[openai,api]>=0.4.0",      # base
  # plus one of:
  "agentkernel[openai,api,redis]>=0.4.0",    # for Redis sessions
  "agentkernel[openai,api,gcp]>=0.4.0",      # for Firestore sessions
]
```

## Terraform Configuration

### Basic Deployment (with Redis)

```hcl
module "serverless_agent" {
  source  = "yaalalabs/ak-serverless/google"
  version = "0.2.14"

  project_id           = var.project_id
  region               = var.region
  product_alias        = var.product_alias
  env_alias            = var.env_alias
  module_name          = var.module_name
  product_display_name = "AK GCP Serverless"

  package_path = "${path.module}/../dist"

  create_redis_cluster = true

  environment_variables = {
    OPENAI_API_KEY = var.openai_api_key
  }

  gateway_endpoints = [
    { path = "app", method = "GET", overwrite_path = "/app" },
    { path = "app_info", method = "POST", overwrite_path = "/app_info" }
  ]
}
```

### With Firestore Sessions

```hcl
module "serverless_agent" {
  source  = "yaalalabs/ak-serverless/google"
  version = "0.2.14"

  project_id           = var.project_id
  region               = var.region
  product_alias        = var.product_alias
  env_alias            = var.env_alias
  module_name          = var.module_name
  product_display_name = "AK GCP Serverless Firestore"

  package_path = "${path.module}/../dist"

  create_firestore_db = true

  environment_variables = {
    OPENAI_API_KEY = var.openai_api_key
  }
}
```

When `create_firestore_db = true`, the module automatically injects:
- `AK_SESSION__TYPE=firestore`
- `AK_SESSION__FIRESTORE__COLLECTION_NAME`

### With JWT Authentication

```hcl
module "serverless_agent" {
  source  = "yaalalabs/ak-serverless/google"
  version = "0.2.14"

  project_id           = var.project_id
  region               = var.region
  product_alias        = var.product_alias
  env_alias            = var.env_alias
  module_name          = var.module_name
  product_display_name = "AK GCP Serverless Auth"

  package_path = "${path.module}/../dist"

  enable_jwt_auth  = true
  jwt_audiences    = ["https://your-api-gateway-url"]

  create_redis_cluster = true

  environment_variables = {
    OPENAI_API_KEY = var.openai_api_key
  }
}
```

## Session Configuration

### Redis Sessions

```yaml
# config.yaml
session:
  type: redis
  redis:
    url: ${REDIS_URL}
    prefix: "ak:myapp:"
    ttl: 604800
```

### Firestore Sessions

```yaml
# config.yaml
session:
  type: firestore
  firestore:
    collection_name: ${AK_SESSION__FIRESTORE__COLLECTION_NAME}
    project_id: ${PROJECT_ID}
    ttl: 604800
```

Enable a Firestore TTL policy on the collection pointing to the `expiry_time` field for automatic document expiry.

## Deployment

```bash
# 1. Build example package
./build.sh

# 2. Deploy infrastructure
cd deploy
terraform init
terraform plan
terraform apply
```

## Key Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `project_id` | ✅ | — | GCP project ID |
| `region` | ✅ | — | GCP region (e.g. `us-central1`) |
| `product_alias` | ✅ | — | Short name for resource naming |
| `env_alias` | ✅ | — | Environment label (e.g. `dev`, `prod`) |
| `module_name` | ✅ | — | Module identifier |
| `package_path` | ✅ | — | Path to Docker build context |
| `create_redis_cluster` | ❌ | `false` | Create Memorystore Redis |
| `create_firestore_db` | ❌ | `false` | Create Firestore database |
| `enable_jwt_auth` | ❌ | `false` | Enable JWT auth on API Gateway |
| `min_instance_count` | ❌ | `0` | Min Cloud Run instances (0 = scale-to-zero) |
| `max_instance_count` | ❌ | `10` | Max Cloud Run instances |

## Outputs

| Output | Description |
|--------|-------------|
| `agent_invoke_url` | Full URL to the API Gateway endpoint |
| `service_url` | Cloud Run service URL (direct, pre-gateway) |

## Examples

See working examples in the repository:

- [`examples/gcp-serverless/openai`](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/gcp-serverless/openai) — Basic deployment with Redis
- [`examples/gcp-serverless/openai-auth`](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/gcp-serverless/openai-auth) — With JWT authentication
- [`examples/gcp-serverless/openai-firestore`](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/gcp-serverless/openai-firestore) — With Firestore sessions

## Teardown

```bash
cd deploy
terraform destroy
```
