---
sidebar_position: 7
---

# GCP Containerized (Cloud Run)

Deploy Agent Kernel agents as always-on containerized services on **GCP Cloud Run** with `min_instance_count ≥ 1`. Uses the `ak-deployment/ak-gcp/containerized` Terraform module.

## Overview

| Component | GCP Service |
|-----------|------------|
| Compute | Cloud Run (always-on, min_instance_count≥1) |
| API Gateway | GCP API Gateway (OpenAPI-based) |
| Container Registry | Artifact Registry |
| Session Store (Redis) | Memorystore Redis |
| Session Store (Firestore) | Firestore (Native Mode) |
| Networking | VPC + VPC Access Connector + Cloud NAT |
| Observability | Cloud Logging (built-in) |

**Key difference from GCP Serverless:** This module defaults to `min_instance_count = 1` — at least one instance is always running, eliminating cold starts and providing consistent low-latency responses.

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

Use `agentkernel.gcp.CloudRun` as the entry point — identical to the serverless variant:

```python
from agentkernel.gcp import CloudRun
from agentkernel.openai import OpenAIModule

OpenAIModule([...])

@CloudRun.register("/version", method="GET")
def version_handler() -> dict:
    return {"version": "1.0.0"}

def main() -> None:
    CloudRun.run()

if __name__ == "__main__":
    main()
```

## Dependencies

```toml
# pyproject.toml
dependencies = [
  "agentkernel[openai,api,redis]>=0.4.0",    # for Redis sessions
  # or: "agentkernel[openai,api,gcp]>=0.4.0"  # for Firestore sessions
]
```

## Terraform Configuration

### Basic Deployment (with Redis, always-on)

```hcl
module "containerized_agent" {
  source = "../../ak-deployment/ak-gcp/containerized"

  project_id           = var.project_id
  region               = var.region
  product_alias        = var.product_alias
  env_alias            = var.env_alias
  module_name          = var.module_name
  product_display_name = "AK GCP Containerized"

  package_path       = "${path.module}/../dist"
  min_instance_count = 1    # always-on
  container_port     = 8000

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

### With JWT Authentication

```hcl
module "containerized_agent" {
  source = "../../ak-deployment/ak-gcp/containerized"

  project_id           = var.project_id
  region               = var.region
  product_alias        = var.product_alias
  env_alias            = var.env_alias
  module_name          = var.module_name
  product_display_name = "AK GCP Containerized Auth"

  package_path       = "${path.module}/../dist"
  min_instance_count = 1
  container_port     = 8000

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
| `container_port` | ❌ | `8000` | Port the container listens on |
| `create_redis_cluster` | ❌ | `false` | Create Memorystore Redis |
| `create_firestore_db` | ❌ | `false` | Create Firestore database |
| `enable_jwt_auth` | ❌ | `false` | Enable JWT auth on API Gateway |
| `min_instance_count` | ❌ | `1` | Min Cloud Run instances (always-on) |
| `max_instance_count` | ❌ | `10` | Max Cloud Run instances |

## Outputs

| Output | Description |
|--------|-------------|
| `agent_invoke_url` | Full URL to the API Gateway endpoint |
| `service_url` | Cloud Run service URL (direct, pre-gateway) |

## When to Choose Containerized vs Serverless

| | Containerized | Serverless |
|-|---------------|------------|
| **Cold starts** | None (min≥1 always warm) | Yes (scale-to-zero) |
| **Cost** | Higher (always-on billing) | Lower (pay per request) |
| **Latency** | Consistent | Variable (first request) |
| **Best for** | Consistent traffic, latency-sensitive | Sporadic workloads |

## Examples

See working examples in the repository:

- [`examples/gcp-containerized/openai`](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/gcp-containerized/openai) — Basic deployment with Redis
- [`examples/gcp-containerized/openai-auth`](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/gcp-containerized/openai-auth) — With JWT authentication

## Teardown

```bash
cd deploy
terraform destroy
```
