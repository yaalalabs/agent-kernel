---
sidebar_position: 7
---

# GCP Containerized (Cloud Run)

Deploy Agent Kernel agents as always-on containerized services on **GCP Cloud Run** with `min_instance_count ≥ 1`. Uses the [`yaalalabs/ak-containerized/google`](https://registry.terraform.io/modules/yaalalabs/ak-containerized/google) Terraform module.

:::note Supported execution modes
Cloud Run runs Agent Kernel's built-in REST server, so it supports synchronous JSON REST **and SSE event streaming** (`execution.mode: rest_sync` with `execution.message_type: delta`) with streaming-capable frameworks (OpenAI Agents SDK, LangGraph, Google ADK, Pydantic AI, Microsoft Agent Framework, Claude Agent SDK). [Queue mode](#queue-mode) (Pub/Sub, the module default) supports `rest_sync` (with SSE) and `rest_async`; WebSocket (`async`) and `realtime` delivery are AWS-only; see the [Deployment Overview](./overview#execution-modes). SSE through API Gateway needs a gateway created with streaming enabled, which Terraform can't do yet, so events may not arrive live.
:::

## Overview

| Component | GCP Service |
|-----------|------------|
| Compute | Cloud Run (always-on, min_instance_count≥1) |
| API Gateway | GCP API Gateway (OpenAPI-based) |
| Container Registry | Artifact Registry |
| Session Store (Redis) | Memorystore Redis |
| Session Store (Firestore) | Firestore (Native Mode) |
| Queue (queue mode) | Pub/Sub topics with dead-letter topics |
| Agent runner (queue mode) | Cloud Run service, pushed to by Pub/Sub |
| Networking | VPC + VPC Access Connector + Cloud NAT |
| Observability | Cloud Logging (built-in) |

**Key difference from GCP Serverless:** This module defaults to `min_instance_count = 1`: at least one instance is always running, eliminating cold starts and providing consistent low-latency responses.

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

Use `agentkernel.gcp.CloudRun` as the entry point, identical to the serverless variant:

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
  "agentkernel[openai,api,redis]>=0.8.1",    # for Redis sessions
  # or: "agentkernel[openai,api,gcp]>=0.8.1"  # for Firestore sessions
]
```

## Terraform Configuration

### Providers

The module is provider-agnostic — it does not configure the `google`/`google-beta`/`docker` providers itself, so your root `main.tf` must configure them and pass them into the module explicitly:

```hcl
provider "google" {
  project = var.project_id
  region  = var.region
}

provider "google-beta" {
  project = var.project_id
  region  = var.region
}

# Docker authenticates against Artifact Registry to push the images this module builds
data "google_client_config" "current" {}

provider "docker" {
  registry_auth {
    address  = "${var.region}-docker.pkg.dev"
    username = "oauth2accesstoken"
    password = data.google_client_config.current.access_token
  }
}
```

Pass them into every `module "containerized_agent"` block below via `providers = { google = google, google-beta = google-beta, docker = docker }`. See the [ak-gcp/containerized module docs](https://github.com/yaalalabs/agent-kernel/tree/develop/ak-deployment/ak-gcp/containerized#-providers) for details.

### Basic Deployment (with Redis, always-on)

```hcl
module "containerized_agent" {
  source    = "yaalalabs/ak-containerized/google"
  version   = "0.8.1"
  providers = { google = google, google-beta = google-beta, docker = docker }

  project_id           = var.project_id
  region               = var.region
  prefix               = var.prefix
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
  source    = "yaalalabs/ak-containerized/google"
  version   = "0.8.1"
  providers = { google = google, google-beta = google-beta, docker = docker }

  project_id           = var.project_id
  region               = var.region
  prefix               = var.prefix
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

## Queue Mode

Queue mode is the module's default (`queue_mode = true`). The deployment becomes two Cloud Run services
built from one image, connected by Pub/Sub:

```
client → API Gateway → edge service ──publish──▶ agent-input ──push──▶ agent-runner service (private)
                            ▲                                                   │
                            └──── pull ◀── agent-output ◀──────── publish ──────┘
                      replies are handed back through Memorystore (Redis)
```

- **Edge** (`CloudRun.run()`): serves the chat API, publishes each request, and answers with the reply.
- **Agent runner** (`CloudRunAgentRunner.run()`): Pub/Sub pushes each request to it; it runs the agents
  and publishes the reply. It is internal-only, and only Pub/Sub's push identity may call it. Cloud Run
  scales it on those pushes, down to zero.
- A session's requests run one at a time, in order: the session id is the Pub/Sub ordering key.
- Failed messages are retried and then copied to a dead-letter topic (`<topic>-dlq`).
- Memorystore is created automatically as the reply store.
- **Trade-off:** Pub/Sub waits at most 600 seconds for the runner to answer a push. An agent run that takes
  longer is redelivered while it is still going and runs a second time. The runner's own request timeout is
  60 minutes, so a long run is never cut off.

The application provides both entry points:

```python
from agentkernel.gcp import CloudRun, CloudRunAgentRunner
from agentkernel.openai import OpenAIModule

OpenAIModule([...])

def main() -> None:      # the edge: the image's CMD
    CloudRun.run()

def runner() -> None:    # the agent runner: agent_runner.command
    CloudRunAgentRunner.run()
```

Its `config.yaml` declares the transport and the stores. Terraform injects only the coordinates (project,
topics, subscription, Redis URL):

```yaml
execution:
  queues:
    type: pubsub
  response_store:
    type: redis
session:
  type: redis
```

```hcl
module "agents" {
  source = "yaalalabs/ak-containerized/google"
  # ...
  execution_mode = "rest_sync" # or rest_async: POST, then poll GET on the chat endpoint

  agent_runner = {
    command            = ["python", "-c", "from app import runner; runner()"]
    min_instance_count = 0
    max_instance_count = 10
    concurrency        = 5 # agent runs per instance
  }
}
```

Enable the `pubsub.googleapis.com` API first. Set `queue_mode = false` for the single-service deployment,
where each instance runs the whole pipeline in one process. See the
[Queue Mode Guide](../advanced/queue-mode-guide#running-queue-mode-on-google-cloud-pubsub) for the transport itself.

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
| `project_id` | ✅ | - | GCP project ID |
| `region` | ✅ | - | GCP region (e.g. `us-central1`) |
| `prefix` | ✅ | - | Prefix applied to every resource name (e.g. `myapp-dev-chat`) |
| `package_path` | ✅ | - | Path to Docker build context |
| `container_port` | ❌ | `8000` | Port the container listens on |
| `create_redis_cluster` | ❌ | `false` | Create Memorystore Redis (queue mode always creates it) |
| `queue_mode` | ❌ | `true` | Edge service + agent-runner service over Pub/Sub; creates Memorystore. `false` deploys the single service |
| `execution_mode` | ❌ | `"rest_sync"` | Queue mode: `rest_sync` or `rest_async` |
| `agent_runner` | ❌ | `{}` | Queue mode: the runner's `command` (or `package_path` / `image_uri`), `cpu`, `memory`, `min_instance_count`, `max_instance_count`, `concurrency` |
| `queue_config` | ❌ | `{}` | Queue mode: `input_queue_max_receive_count` / `output_queue_max_receive_count` (deliveries before dead-lettering, default 5), `batch_size` |
| `create_firestore_db` | ❌ | `false` | Create Firestore database |
| `enable_jwt_auth` | ❌ | `false` | Enable JWT auth on API Gateway |
| `min_instance_count` | ❌ | `1` | Min Cloud Run instances (always-on) |
| `max_instance_count` | ❌ | `10` | Max Cloud Run instances |

## Outputs

| Output | Description |
|--------|-------------|
| `agent_invoke_url` | Full URL to the API Gateway endpoint |
| `service_url` | Cloud Run service URL (direct, pre-gateway) |
| `input_topic` | Pub/Sub topic carrying chat requests (queue mode) |
| `agent_runner_service` | The agent-runner Cloud Run service (queue mode) |

## When to Choose Containerized vs Serverless

| | Containerized | Serverless |
|-|---------------|------------|
| **Cold starts** | None (min≥1 always warm) | Yes (scale-to-zero) |
| **Cost** | Higher (always-on billing) | Lower (pay per request) |
| **Latency** | Consistent | Variable (first request) |
| **Best for** | Consistent traffic, latency-sensitive | Sporadic workloads |

## Examples

See working examples in the repository:

- [`examples/gcp-containerized/openai`](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/gcp-containerized/openai): Basic deployment with Redis
- [`examples/gcp-containerized/openai-auth`](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/gcp-containerized/openai-auth): With JWT authentication
- [`examples/gcp-serverless/openai-queue-mode`](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/gcp-serverless/openai-queue-mode): Queue mode on the serverless module; the containerized module takes the same `queue_mode` and `agent_runner` inputs

## Teardown

```bash
cd deploy
terraform destroy
```
