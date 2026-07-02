---
name: ak-cloud-deploy
description: >
  Deploy an Agent Kernel project to AWS, Azure, or GCP using Terraform modules.
  Supports serverless and containerized modes for all three clouds. AWS supports
  execution modes (rest_sync, rest_async, async), queue-based scalable processing,
  and custom API Gateway authorizers. GCP supports Cloud Run serverless (scale-to-zero)
  and containerized (always-on) with Redis or Firestore session backends.
license: Apache-2.0
metadata:
  author: yaalalabs
  version: "0.6.0"
  category: user
---

# Deploy to Cloud

Use this skill to deploy your Agent Kernel project to AWS, Azure, or GCP.

## Instructions for the Agent

When the user wants cloud deployment, follow this workflow.

### Step 1: Identify the Project

Check for:
- `pyproject.toml` with `agentkernel` dependency
- agent entry file (`app.py`, `lambda.py`, or similar)
- `config.yaml`

If missing, suggest `ak-init` first.

### Step 2: Ask Deployment Questions

1. Cloud provider: AWS, Azure, or GCP?
2. Runtime mode:
- Serverless
- Containerized
3. Execution pattern (AWS serverless only):
- Synchronous HTTP (`rest_sync`, supports standard or queue/scalable mode)
- Asynchronous REST (`rest_async`, queue/scalable mode)
- WebSocket async (`async`, queue/scalable mode)
4. Scalability (AWS serverless only): standard or queue/scalable mode?
5. Session store: Redis, DynamoDB (AWS), Cosmos DB (Azure), Firestore (GCP)?
6. Security: custom authorizer required (AWS serverless only)?
7. Environment aliases: `product_alias`, `env_alias`, `module_name`.

### Step 3: Choose the Correct Terraform Module

Use official modules:
- AWS serverless: `yaalalabs/ak-serverless/aws`
- AWS containerized: `yaalalabs/ak-containerized/aws`
- Azure serverless: `yaalalabs/ak-serverless/azurerm`
- Azure containerized: `yaalalabs/ak-containerized/azurerm`
- GCP serverless: `yaalalabs/ak-serverless/google`
- GCP containerized: `yaalalabs/ak-containerized/google`

Use current module version (`0.6.0`) unless user requests another.

AWS-only features in this skill:
- `execution_mode`
- `queue_mode`
- `authorizer`

Azure examples use the provider module's standard top-level inputs (`function_name`, `package_path`, `container_port`, `publisher_email`) rather than AWS serverless execution modes.

GCP modules use Cloud Run for both serverless (scale-to-zero, `min_instance_count=0`) and containerized (always-on, `min_instance_count≥1`) modes. Both use `agentkernel.gcp.CloudRun` as the entry point.

### Step 4: Align App Dependencies and Session Config

When the user selects a session store, always update both app dependencies and `config.yaml`.

#### Redis sessions

- Dependency extras: include `redis`
- Typical dependency example:

```toml
dependencies = [
  "agentkernel[openai,api,redis]>=0.6.0"
]
```

- `config.yaml` session block:

```yaml
session:
  type: redis
  namespace: chat
  redis:
    host: ${REDIS_HOST}
    port: 6379
    db: 0
```

#### DynamoDB sessions (AWS)

- Dependency extras: include `aws`
- Typical dependency example:

```toml
dependencies = [
  "agentkernel[openai,api,aws]>=0.6.0"
]
```

- `config.yaml` session block:

```yaml
session:
  type: dynamodb
  dynamodb:
    table_name: ${DYNAMODB_MEMORY_TABLE}
    region: ${AWS_REGION}
```

#### Cosmos DB sessions (Azure)

- Dependency extras: include `azure`
- Typical dependency example:

```toml
dependencies = [
  "agentkernel[openai,api,azure]>=0.6.0"
]
```

- `config.yaml` session block:

```yaml
session:
  type: cosmosdb
  cosmosdb:
    endpoint: ${AZURE_COSMOS_ENDPOINT}
    database_name: ${AZURE_COSMOS_DATABASE}
    container_name: ${AZURE_COSMOS_CONTAINER}
```

#### Firestore sessions (GCP)

- Dependency extras: include `gcp`
- Typical dependency example:

```toml
dependencies = [
  "agentkernel[openai,api,gcp]>=0.6.0"
]
```

- `config.yaml` session block:

```yaml
session:
  type: firestore
  firestore:
    collection_name: ${AK_SESSION__FIRESTORE__COLLECTION_NAME}
    project_id: ${PROJECT_ID}
    ttl: 604800
```

- The Terraform module injects `AK_SESSION__TYPE=firestore` and `AK_SESSION__FIRESTORE__COLLECTION_NAME` automatically when Firestore is enabled.
- A TTL policy must be set on the Firestore collection pointing to the `expiry_time` field for automatic document expiry.

If the Terraform module creates the backing store (for example `create_redis_cluster = true` or `create_dynamodb_memory_table = true`), make sure output values are wired to the app environment variables used by `config.yaml`.

## AWS Serverless (Lambda + API Gateway)

### Agent Code Pattern

Use Lambda handler entrypoint:

```python
from agentkernel.aws import Lambda
from agentkernel.openai import OpenAIModule

# Register agents with your framework module
OpenAIModule([...])

handler = Lambda.handler
```

### A) Basic Synchronous REST (`rest_sync`)

Use this for straightforward request/response APIs.

This is the single-Lambda pattern: use `request_handler` plus any `gateway_endpoints`. Do not add `agent_runner` or `response_handler` unless you are using queue mode.

```hcl
module "serverless_agents" {
  source  = "yaalalabs/ak-serverless/aws"
  version = "0.6.0"

  product_alias        = var.product_alias
  env_alias            = var.env_alias
  module_name          = var.module_name
  product_display_name = "AK Serverless"
  region               = var.region

  execution_mode = "rest_sync"

  request_handler = {
    module_name          = "request-handler"
    function_name        = "chat-handler"
    function_description = "AK request handler"
    handler_path         = "lambda.handler"
    package_type         = "Image"
    package_path         = "../dist"
    timeout              = 45
    memory_size          = 256
    environment_variables = {
      OPENAI_API_KEY = var.openai_api_key
    }
  }

  gateway_endpoints = [
    { path = "app", method = "GET" },
    { path = "app_info", method = "POST" }
  ]
}
```

### B) Scalable Queue Mode (`rest_sync` or `rest_async`)

Use this for high throughput and long-running requests.

This is the multi-artifact pattern used by the scalable example: a request handler zip, an agent-runner image, and a response-handler zip.

Each Lambda can use one of three `package_type` values:


| `package_type` | Artifact source                    | Required field(s)                                    | What Terraform does                                                                                                                                                                                       |
| -------------- | ---------------------------------- | ---------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `LocalZip`     | Local ZIP file or source directory | `package_path`                                       | Uses the Lambda module's local packaging support. No shared source bucket is managed by this module.                                                                                                      |
| `S3Zip`        | ZIP artifact stored in S3          | **Either** `package_path` **or** `lambda_package_s3` | If `package_path` is provided, this module creates/uses a shared source bucket, uploads the ZIP, and deploys from S3. If `lambda_package_s3` is provided, Terraform uses the existing S3 object directly. |
| `Image`        | Container image in ECR             | **Either** `ecr_image_uri` **or** `package_path`     | If `ecr_image_uri` is provided, Terraform uses the existing image. If `package_path` is provided, Terraform builds and pushes an image to ECR and deploys it.                                             |


`package_path` and `lambda_package_s3`/`ecr_image_uri` are mutually exclusive — set only one.

**Development / local build** (build artifacts locally before running `terraform apply`):

```hcl
module "serverless_agents" {
  source  = "yaalalabs/ak-serverless/aws"
  version = "0.6.0"

  product_alias      = var.product_alias
  env_alias          = var.env_alias
  module_name        = var.module_name
  region             = var.region
  product_display_name = "AK Scalable REST"

  queue_mode     = true
  execution_mode = "rest_sync" # can also be "rest_async"

  create_dynamodb_memory_table   = true
  create_dynamodb_response_store = true

  request_handler = {
    module_name          = "rqst-hdlr"
    function_name        = "request-handler"
    function_description = "Receives REST requests"
    handler_path         = "lambda_request_handler.handler"
    package_type         = "LocalZip"
    package_path         = "../dist_request_handler.zip"
    timeout              = 45
    memory_size          = 256
    environment_variables = {
      OPENAI_API_KEY = var.openai_api_key
    }
  }

  agent_runner = {
    module_name          = "agent-runner"
    function_name        = "agent-runner"
    function_description = "Processes queued requests"
    handler_path         = "lambda_agent_runner.handler"
    package_type         = "Image"
    package_path         = "../dist_agent_runner"
    timeout              = 45
    memory_size          = 512
    environment_variables = {
      OPENAI_API_KEY = var.openai_api_key
    }
  }

  response_handler = {
    module_name          = "response-handler"
    function_name        = "response-handler"
    function_description = "Handles async response completion"
    handler_path         = "lambda_response_handler.handler"
    package_type         = "LocalZip"
    package_path         = "../dist_response_handler.zip"
    timeout              = 45
    memory_size          = 256
  }

  queue_config = {
    input_queue_visibility_timeout         = 60
    input_queue_max_receive_count          = 3
    input_queue_create_dlq                 = false
    input_queue_message_retention_seconds  = 300
    output_queue_visibility_timeout        = 60
    output_queue_max_receive_count         = 3
    output_queue_create_dlq                = false
    output_queue_message_retention_seconds = 300
    batch_size                             = 10
    maximum_batching_window_in_seconds     = 0
  }
}
```

**Production: external artifact sources (S3 / ECR)**

Build and push artifacts in CI/CD, then point Terraform at them so `terraform apply` contains no local build step:

```hcl
  request_handler = {
    module_name      = "rqst-hdlr"
    function_name    = "request-handler"
    handler_path     = "lambda_request_handler.handler"
    package_type     = "S3Zip"
    lambda_package_s3 = {
      bucket = "my-lambda-packages-bucket"
      key    = "dist_request_handler.zip"
    }
    timeout     = 45
    memory_size = 256
    environment_variables = { OPENAI_API_KEY = var.openai_api_key }
  }

  agent_runner = {
    module_name   = "agent-runner"
    function_name = "agent-runner"
    handler_path  = "lambda_agent_runner.handler"
    package_type  = "Image"
    ecr_image_uri = "123456789012.dkr.ecr.us-west-2.amazonaws.com/agent-runner:latest"
    timeout       = 45
    memory_size   = 512
    environment_variables = { OPENAI_API_KEY = var.openai_api_key }
  }

  response_handler = {
    module_name      = "response-handler"
    function_name    = "response-handler"
    handler_path     = "lambda_response_handler.handler"
    package_type     = "S3Zip"
    lambda_package_s3 = {
      bucket = "my-lambda-packages-bucket"
      key    = "dist_response_handler.zip"
    }
    timeout     = 45
    memory_size = 256
  }
```

See [examples/aws-serverless/scalable-openai](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/aws-serverless/scalable-openai) for a complete working example of this pattern.

**Queue mode `config.yaml`** (bundled into every Lambda package — `execution.mode`, queue URLs, table names, and `max_receive_count` are all injected automatically by Terraform as environment variables; only set values that are NOT injected):

```yaml
# For rest_sync or rest_async
execution:
  response_store:
    type: dynamodb  # or redis — not injected, must be set here
    retry_count: 5
    delay: 5
session:
  type: dynamodb  # or redis — not injected, must be set here
```

- `rest_sync`: request handler sends to queue, polls the response store until the result is available, then returns it synchronously.
- `rest_async`: request handler returns `{status: "ACCEPTED", request_id}` immediately; the client polls `GET /api/{version}/{endpoint}` with `{"request_id": "<id>"}` in the JSON body.
- SQS visibility timeout for each queue **must be >= the corresponding Lambda timeout**.

**Required `pyproject.toml` extras for queue mode**:

```toml
dependencies = [
  "agentkernel[openai,api,aws]>=0.6.0"  # include 'redis' if using Redis session/response store
]
```

### C) WebSocket Async (`async`)

Use this for realtime bidirectional interactions.

This follows the current websocket example shape: the request handler stays on the module's top-level Lambda inputs, then queue workers and WebSocket handlers are added via nested blocks.

```hcl
module "serverless_agents" {
  source  = "yaalalabs/ak-serverless/aws"
  version = "0.6.0"

  product_alias        = var.product_alias
  env_alias            = var.env_alias
  module_name          = var.module_name
  region               = var.region
  product_display_name = "AK WebSocket Serverless Example"

  queue_mode     = true
  execution_mode = "async"

  create_redis_cluster           = true
  create_dynamodb_response_store = true

  request_handler = {
    module_name          = "request-handler"
    function_name        = "request-handler"
    function_description = "Receives WebSocket requests"
    handler_path         = "lambda_request_handler.handler"
    package_type         = "LocalZip"
    package_path         = "../dist_request_handler.zip"
    timeout              = 45
    memory_size          = 256
    environment_variables = {
      OPENAI_API_KEY = var.openai_api_key
    }
  }

  agent_runner = {
    module_name          = "agent-runner"
    function_name        = "agent-runner"
    function_description = "Processes chat tasks"
    handler_path         = "lambda_agent_runner.handler"
    package_type         = "Image"
    package_path         = "../dist_agent_runner"
    timeout              = 45
    memory_size          = 512
    environment_variables = {
      OPENAI_API_KEY = var.openai_api_key
    }
  }

  response_handler = {
    module_name          = "response-handler"
    function_name        = "response-handler"
    function_description = "Sends responses to connections"
    handler_path         = "lambda_response_handler.handler"
    package_type         = "LocalZip"
    package_path         = "../dist_response_handler.zip"
    timeout              = 45
    memory_size          = 256
  }

  ws_connection_handler = {
    module_name          = "ws-connection-handler"
    function_name        = "ws-connection-handler"
    function_description = "Handles $connect/$disconnect"
    handler_path         = "lambda_ws_connection_handler.handler"
    package_path         = "../dist_ws_connection_handler.zip"
    timeout              = 45
    memory_size          = 256
  }

  ws_routes = [
    { route = "app" },
    { route = "app_info" }
  ]
}
```

**WebSocket `lambda_ws_connection_handler.py`** — implement `AuthValidator` to validate the bearer token on `$connect`:

```python
import jwt
import os
from agentkernel.auth import AuthValidator, ValidationResult
from agentkernel.aws import WebsocketConnectionHandler


class MyAuthValidator(AuthValidator):
    def validate(self, token: str) -> ValidationResult:
        try:
            payload = jwt.decode(
                token,
                os.environ["JWT_SECRET"],
                algorithms=["HS256"],
                issuer=os.environ["JWT_ISSUER"],
                audience=os.environ["JWT_AUDIENCE"],
            )
            user_id = payload.get("userId", "")
            if user_id:
                return ValidationResult(is_valid=True, claims={"userId": user_id})
            return ValidationResult(is_valid=False, error_msg="userId claim missing")
        except Exception as e:
            return ValidationResult(is_valid=False, error_msg=str(e))


handler = WebsocketConnectionHandler.set_auth_validator(MyAuthValidator()).handler
```

**WebSocket `lambda_request_handler.py`** — routes are registered by **route name** (no leading slash, no HTTP method) because the WebSocket API uses `$request.body.route` for dispatch:

```python
import json
from agentkernel.aws import Lambda


@Lambda.register("app")               # WebSocket route name, no slash/method
def app_handler(event, context):
    return {"response": "Hello from app route"}


@Lambda.register("app_info")
def app_info_handler(event, context):
    payload = json.loads(event.get("body") or "{}")
    return {"response": "Hello from app_info route"}


handler = Lambda.handler
```

Contrast with REST mode where routes use a leading slash and HTTP method:
```python
@Lambda.register("/app", method="GET")    # REST mode: path + method
```

**WebSocket `config.yaml`** (bundled into every Lambda package — `execution.mode`, `websocket_api.chat_route`, queue URLs, and connection table name are all injected automatically by Terraform; only set values that are NOT injected):

```yaml
session:
  type: redis                   # or dynamodb — not injected, must be set here
  redis:
    prefix: "ak:myapp:"
```

- Authentication is **mandatory** for WebSocket mode. `AuthValidator.validate()` must return `claims["userId"]`; connections without a valid token are rejected at `$connect`.
- The `authorizer` Terraform block is not supported in WebSocket mode — leave it unset.
- Only `LocalZip` is supported for `ws_connection_handler.package_path`.
- `ws_routes` custom routes must have a matching `@Lambda.register("route_name")` entry. `ws_chat_route` is the built-in AI chat route — it is handled internally by the framework and does **not** need a `@Lambda.register` entry.

**Required `pyproject.toml` extras for WebSocket mode**:

```toml
dependencies = [
  "agentkernel[openai,api,aws,redis,auth]>=0.6.0"
]
```

### D) API Gateway Custom Authorizer (AWS)

If the user needs token verification, include `authorizer` block:

```hcl
authorizer = {
  description           = "API Gateway Lambda Authorizer"
  function_name         = "gateway-authorizer"
  handler_path          = "lambda_auth.handler"
  package_path          = "../dist_auth.zip"
  package_type          = "LocalZip"
  module_name           = "auth-module"
  result_ttl_in_seconds = 0
  environment_variables = {
    SOME_OTHER_KEY = "Some Other Value"
  }
}
```

## AWS Containerized (ECS/Fargate)

### Agent Code Pattern

```python
from agentkernel.api import RESTAPI
from agentkernel.openai import OpenAIModule

OpenAIModule([...])

if __name__ == "__main__":
    RESTAPI.run()
```

### Terraform Example

**Local build (development)** — `package_path` points to the Docker build context:

```hcl
module "containerized_agents" {
  source  = "yaalalabs/ak-containerized/aws"
  version = "0.6.0"

  product_alias        = var.product_alias
  env_alias            = var.env_alias
  module_name          = var.module_name
  package_path         = "../dist"
  region               = var.region
  product_display_name = "AK ECS Deployment"

  ecs_container_port = 8000
  ecs_desired_count  = 2

  create_dynamodb_memory_table = true

  environment_variables = {
    OPENAI_API_KEY = var.openai_api_key
  }
}
```

**Production: pre-built ECR image** — set `ecr_image_uri` instead of `package_path`. Terraform skips the local Docker build and deploys the specified image directly:

```hcl
module "containerized_agents" {
  source  = "yaalalabs/ak-containerized/aws"
  version = "0.6.0"

  product_alias        = var.product_alias
  env_alias            = var.env_alias
  module_name          = var.module_name
  ecr_image_uri        = "123456789012.dkr.ecr.us-west-2.amazonaws.com/my-app:v1.2.3"
  region               = var.region
  product_display_name = "AK ECS Deployment"

  ecs_container_port = 8000
  ecs_desired_count  = 2

  create_dynamodb_memory_table = true

  environment_variables = {
    OPENAI_API_KEY = var.openai_api_key
  }
}
```

`package_path` and `ecr_image_uri` are mutually exclusive; exactly one must be set.

See [examples/aws-containerized/openai-dynamodb](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/aws-containerized/openai-dynamodb) for a complete example using an external ECR image.

## Azure Serverless (Functions + APIM)

### Agent Code Pattern

```python
from agentkernel.azure import AzureFunctions
from agentkernel.openai import OpenAIModule

OpenAIModule([...])

handler = AzureFunctions.handler
```

### Terraform Example

```hcl
module "serverless_agents" {
  source  = "yaalalabs/ak-serverless/azurerm"
  version = "0.6.0"

  product_alias        = var.product_alias
  env_alias            = var.env_alias
  module_name          = var.module_name
  region               = var.region
  resource_group_name  = var.resource_group_name
  publisher_email      = var.publisher_email
  product_display_name = "AK Azure Functions Example"

  function_name        = "openai-agents"
  function_description = "Agent Kernel OpenAI Sample Azure Function"
  module_type          = "python"
  package_path         = "../dist.zip"
  create_redis_cluster = true

  create_cosmosdb_cluster = false

  environment_variables = {
    OPENAI_API_KEY = var.openai_api_key
  }

  gateway_endpoints = [
    {
      function_name = "AgentFunction"
      path          = "/chat"
      method        = "POST"
    },
    {
      function_name = "CustomFunction"
      path          = "/custom"
      method        = "POST"
    }
  ]
}
```

## Azure Containerized (Container Apps + APIM)

### Terraform Example

```hcl
module "containerized_agents" {
  source  = "yaalalabs/ak-containerized/azurerm"
  version = "0.6.0"

  product_alias        = var.product_alias
  env_alias            = var.env_alias
  module_name          = var.module_name
  region               = var.region
  resource_group_name  = var.resource_group_name
  publisher_email      = var.publisher_email
  package_path         = "../dist"
  product_display_name = "AK Azure Container Apps"

  container_port = 8000

  create_cosmosdb_cluster = true

  environment_variables = {
    OPENAI_API_KEY = var.openai_api_key
  }
}
```

## GCP Serverless (Cloud Run — scale-to-zero)

### Agent Code Pattern

```python
from agentkernel.gcp import CloudRun
from agentkernel.openai import OpenAIModule

OpenAIModule([...])

@CloudRun.register("/app", method="GET")
def app_handler() -> dict:
    return {"status": "ok"}

def main() -> None:
    CloudRun.run()
```

### Terraform Example (with Redis sessions)

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

### Terraform Example (with Firestore sessions)

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

The module injects `AK_SESSION__TYPE=firestore` and `AK_SESSION__FIRESTORE__COLLECTION_NAME` automatically when `create_firestore_db = true`.

**Required `pyproject.toml` extras:**

```toml
dependencies = [
  "agentkernel[openai,api,gcp]>=0.6.0"      # for Firestore sessions
  # or: "agentkernel[openai,api,redis]>=0.6.0"  # for Redis sessions
]
```

## GCP Containerized (Cloud Run — always-on)

### Agent Code Pattern

Same as GCP Serverless — use `agentkernel.gcp.CloudRun`:

```python
from agentkernel.gcp import CloudRun
from agentkernel.openai import OpenAIModule

OpenAIModule([...])

def main() -> None:
    CloudRun.run()
```

### Terraform Example

```hcl
module "containerized_agent" {
  source  = "yaalalabs/ak-containerized/google"
  version = "0.2.14"

  project_id           = var.project_id
  region               = var.region
  product_alias        = var.product_alias
  env_alias            = var.env_alias
  module_name          = var.module_name
  product_display_name = "AK GCP Containerized"

  package_path       = "${path.module}/../dist"
  min_instance_count = 1   # always-on — no cold starts
  container_port     = 8000

  create_redis_cluster = true

  environment_variables = {
    OPENAI_API_KEY = var.openai_api_key
  }
}
```

**Key difference from GCP Serverless:** `min_instance_count = 1` keeps at least one instance running at all times, eliminating cold starts.

## Config and Packaging Notes

### Packaging

For AWS async/scalable deployments, build and package separately:
- **request handler** — `LocalZip`, `S3Zip`, or `Image`
- **agent runner** — `LocalZip`, `S3Zip`, or `Image` (typically `Image` for heavier dependencies)
- **response handler** — `LocalZip`, `S3Zip`, or `Image`
- **ws-connection-handler** — `LocalZip` only (WebSocket mode; no `package_type` field, only `package_path`)

Azure serverless uses a single zip `package_path` for the Functions deployment.
Azure containerized uses `package_path` as the Docker build context for Container Apps.

### config.yaml per mode

Each Lambda package must include a `config.yaml`. Most runtime values (`execution.mode`, queue URLs, table names, `max_receive_count`, `websocket_api.chat_route`) are **injected automatically by Terraform as environment variables** and do not need to be set in `config.yaml`. Only the values in the table below must be configured manually:

| Config key | Required in | Notes |
|------------|------------|-------|
| `execution.response_store.type` | request-handler, response-handler (queue modes) | `redis` or `dynamodb` — not injected |
| `execution.response_store.retry_count` | request-handler (`rest_sync`) | how many times to poll for response |
| `execution.response_store.delay` | request-handler (`rest_sync`) | seconds between polls |
| `session.type` | agent-runner | `redis` or `dynamodb` — not injected |
| `session.redis.prefix` | agent-runner (Redis sessions) | key namespace prefix |

### Timeouts and visibility

- SQS `input_queue_visibility_timeout` must be **>= agent runner Lambda timeout**.
- SQS `output_queue_visibility_timeout` must be **>= response handler Lambda timeout**.
- FIFO queues are used by default; `message_group_id` maps to session ID.

## Prerequisites Checklist

### AWS

- AWS CLI configured (`aws configure`)
- Terraform >= 1.9.5
- S3 bucket for remote state (optional but recommended)
- DynamoDB table for state lock (optional but recommended)
- Container registry access (if `package_type = "Image"`)

### Azure

- Azure CLI logged in (`az login`)
- Terraform >= 1.9.5
- Resource group and subscription permissions
- Storage for remote Terraform state (optional but recommended)

### GCP

- GCP CLI configured (`gcloud auth application-default login`)
- Terraform >= 1.9.5
- Docker installed (for local image building and push to Artifact Registry)
- An existing GCP project with appropriate permissions
- Required APIs enabled: Cloud Run, API Gateway, Artifact Registry, VPC Access

## Deploy

```bash
cd deploy
terraform init
terraform plan
terraform apply
```

## Teardown

```bash
cd deploy
terraform destroy
```

## What to Do Next

- Add capabilities (`ak-add-capabilities`) before production rollout.
- Add tests (`ak-test`) against deployed endpoints.
- Add integrations (`ak-add-integration`) for Slack/WhatsApp/Telegram/Teams.
- Iterate on tools and agents (`ak-build`) and re-run `terraform apply`.
