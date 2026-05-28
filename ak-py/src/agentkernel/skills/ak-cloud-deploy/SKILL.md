---
name: ak-cloud-deploy
description: >
  Deploy an Agent Kernel project to AWS or Azure using Terraform modules.
  Supports serverless and containerized modes, plus AWS execution modes
  (rest_sync, rest_async, async), queue-based scalable processing, custom
  API Gateway authorizers, and multi-lambda serverless patterns.
license: Apache-2.0
metadata:
  author: yaalalabs
  version: "0.4.0"
  category: user
---

# Deploy to Cloud

Use this skill to deploy your Agent Kernel project to AWS or Azure.

## Instructions for the Agent

When the user wants cloud deployment, follow this workflow.

### Step 1: Identify the Project

Check for:
- `pyproject.toml` with `agentkernel` dependency
- agent entry file (`app.py`, `lambda.py`, or similar)
- `config.yaml`

If missing, suggest `ak-init` first.

### Step 2: Ask Deployment Questions

1. Cloud provider: AWS or Azure?
2. Runtime mode:
- Serverless
- Containerized
3. Execution pattern (AWS serverless only):
- Synchronous HTTP (`rest_sync`, supports standard or queue/scalable mode)
- Asynchronous REST (`rest_async`, queue/scalable mode)
- WebSocket async (`async`, queue/scalable mode)
4. Scalability (AWS serverless only): standard or queue/scalable mode?
5. Session store: Redis, DynamoDB (AWS), Cosmos DB (Azure)?
6. Security: custom authorizer required (AWS serverless only)?
7. Environment aliases: `product_alias`, `env_alias`, `module_name`.

### Step 3: Choose the Correct Terraform Module

Use official modules:
- AWS serverless: `yaalalabs/ak-serverless/aws`
- AWS containerized: `yaalalabs/ak-containerized/aws`
- Azure serverless: `yaalalabs/ak-serverless/azurerm`
- Azure containerized: `yaalalabs/ak-containerized/azurerm`

Use current module version (`0.4.0`) unless user requests another.

AWS-only features in this skill:
- `execution_mode`
- `queue_mode`
- `authorizer`

Azure examples use the provider module's standard top-level inputs (`function_name`, `package_path`, `container_port`, `publisher_email`) rather than AWS serverless execution modes.

### Step 4: Align App Dependencies and Session Config

When the user selects a session store, always update both app dependencies and `config.yaml`.

#### Redis sessions

- Dependency extras: include `redis`
- Typical dependency example:

```toml
dependencies = [
  "agentkernel[openai,api,redis]>=0.4.0"
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
  "agentkernel[openai,api,aws]>=0.4.0"
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
  "agentkernel[openai,api,azure]>=0.4.0"
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
  version = "0.4.0"

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

```hcl
module "serverless_agents" {
  source  = "yaalalabs/ak-serverless/aws"
  version = "0.4.0"

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

### C) WebSocket Async (`async`)

Use this for realtime bidirectional interactions.

This follows the current websocket example shape: the request handler stays on the module's top-level Lambda inputs, then queue workers and WebSocket handlers are added via nested blocks.

```hcl
module "serverless_agents" {
  source  = "yaalalabs/ak-serverless/aws"
  version = "0.4.0"

  product_alias = var.product_alias
  env_alias     = var.env_alias
  function_description = "Agent Kernel OpenAI Scalable Sample Lambda"
  function_name        = "request-handler"
  module_name   = var.module_name
  handler_path  = "lambda_request_handler.handler"
  package_path  = "../dist_request_handler.zip"
  package_type  = "LocalZip"
  memory_size   = 256
  timeout       = 45
  region        = var.region

  queue_mode     = true
  execution_mode = "async"

  create_redis_cluster            = true
  create_dynamodb_response_store  = true

  environment_variables = {
    OPENAI_API_KEY = var.openai_api_key
  }

  agent_runner = {
    module_name          = "agent-runner"
    function_name        = "agent-runner"
    function_description = "Processes chat tasks"
    handler_path         = "lambda_agent_runner.handler"
    package_type         = "Image"
    package_path         = "../dist_agent_runner"
  }

  response_handler = {
    module_name          = "response-handler"
    function_name        = "response-handler"
    function_description = "Sends responses to connections"
    handler_path         = "lambda_response_handler.handler"
    package_type         = "LocalZip"
    package_path         = "../dist_response_handler.zip"
  }

  ws_connection_handler = {
    module_name          = "ws-connection-handler"
    function_name        = "ws-connection-handler"
    function_description = "Handles $connect/$disconnect"
    handler_path         = "lambda_ws_connection_handler.handler"
    package_type         = "LocalZip"
    package_path         = "../dist_ws_connection_handler.zip"
  }

  ws_routes = [
    { route = "app" },
    { route = "app_info" }
  ]
}
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

```hcl
module "containerized_agents" {
  source  = "yaalalabs/ak-containerized/aws"
  version = "0.4.0"

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
  version = "0.4.0"

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
  version = "0.4.0"

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

## Config and Packaging Notes

- For AWS async/scalable deployments, split packaging for:
- request handler
- agent runner
- response handler
- (WebSocket mode) connection handler
- Azure serverless uses a single zip `package_path` for the Functions deployment.
- Azure containerized uses `package_path` as the Docker build context for Container Apps.
- Ensure `config.yaml` session settings align with Terraform-created stores.
- Keep Lambda timeout lower than SQS visibility timeout.

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
