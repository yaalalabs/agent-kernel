
## AWS Serverless WebSocket + OpenAI Example

This example deploys **Agent Kernel** on AWS using the `yaalalabs/ak-serverless/aws` Terraform module and exposes:

- A REST API (custom endpoints: `/api/app`, `/api/app_info`)
- A WebSocket API (connect/disconnect handled by `lambda_ws_connection_handler.py`)
- An async execution pipeline (request handler -> queue -> agent runner -> response handler)

The deployment provisions supporting infrastructure (SQS, API Gateway, and a Redis cluster and DynamoDB response store as configured in Terraform).

## What gets deployed

- **Request handler (Zip Lambda)**
  - Code: `lambda_request_handler.py`
  - Package: `dist_request_handler.zip`
- **Agent runner (Container/Image Lambda)**
  - Code: `lambda_agent_runner.py`
  - Image context: `dist_agent_runner/`
- **Response handler (Zip Lambda)**
  - Code: `lambda_response_handler.py`
  - Package: `dist_response_handler.zip`
- **WebSocket connection handler (Zip Lambda)**
  - Code: `lambda_ws_connection_handler.py`
  - Package: `dist_ws_connection_handler.zip`

## Configuration

### Python dependencies

Project dependencies are declared in `pyproject.toml`:

- `agentkernel[aws,openai,redis]>=0.3.3`

### Agent Kernel runtime config

`config.yaml` is bundled into each Lambda package/image. Update it if you need to point at a different Redis endpoint or adjust execution/response-store settings.

Note: this example repository currently contains a concrete Redis URL in `config.yaml`. For real deployments, you typically want this to be injected via environment variables or updated as part of deployment.

### Terraform variables

Terraform variables are declared in `deploy/variables.tf`:

- `region`
- `product_alias`
- `env_alias`
- `module_name`
- `is_production`
- `openai_api_key` (sensitive)

Provide values via `terraform.tfvars` (recommended) or via `-var` flags.

## Deploy

1. Ensure a `requirements.txt` exists next to the Lambda files (the deploy script installs from it).
   - If you use `uv`, you can generate one in this folder before deploying.

2. From `examples/aws-serverless/websocket-openai/deploy/` run:

```bash
./deploy.sh
```

This script:

- Builds Zip packages for request/response/ws-connection handlers
- Builds the container image context for the agent runner
- Runs `terraform init` and `terraform apply`

## Outputs

After apply, Terraform outputs:

- `websocket_api_endpoint_url`

See `deploy/outputs.tf`.

## Using the WebSocket API

The WebSocket `$connect` route is protected by a custom token validator in `lambda_ws_connection_handler.py`.

- The validator decodes a JWT (signature verification is disabled in this example).
- The connection is allowed only if the JWT payload contains `email: "test@test.com"`.

### Example token

Any JWT-formatted token with an `email` claim set to `test@test.com` will pass validation.

If you don’t already have a JWT handy, you can generate an unsigned token for testing with any JWT tool/library.

## Custom REST endpoints

The request handler registers two example endpoints:

- `GET /api/app`
- `POST /api/app_info`

These are configured as `gateway_endpoints` in `deploy/main.tf`.

## Cleanup

From `examples/aws-serverless/websocket-openai/deploy/` run:

```bash
terraform destroy
```

