
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

- `agentkernel[aws,openai,redis]>=0.8.1`

### Agent Kernel runtime config

`config.yaml` is bundled into each Lambda package/image. Update it if you need to point at a different Redis endpoint or adjust execution/response-store settings.

Note: this example repository currently contains a concrete Redis URL in `config.yaml`. For real deployments, you typically want this to be injected via environment variables or updated as part of deployment.

### Terraform variables

Terraform variables are declared in `deploy/variables.tf`:

- `region`
- `prefix`
- `is_production`
- `demo_auth_token` (the credential the `$connect` handshake accepts; see [Using the WebSocket API](#using-the-websocket-api))

Provide values via `terraform.tfvars` (recommended) or via `-var` flags.

The OpenAI key is not a Terraform variable: store it in SSM Parameter Store, where `<prefix>` is
`prefix` in `deploy/terraform.tfvars`. The deployment sets `ssm_enabled = true` and `config.yaml` selects
the `aws_ssm` secret provider, so the agent runner reads it from SSM at startup:

```bash
aws ssm put-parameter --name "/ak/<prefix>/openai_api_key" \
    --type SecureString --value "$OPENAI_API_KEY" --overwrite
```

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
- `websocket_api_stage_name`

See `deploy/outputs.tf`.

## Using the WebSocket API

To connect to the WebSocket API, combine the outputs to form the complete endpoint URL:

```bash
{websocket_api_endpoint_url}/{websocket_api_stage_name}?token=<credential>
```

For example:
```bash
wss://abc123.execute-api.us-east-1.amazonaws.com/prod?token=<the demo_auth_token value>
```

The `$connect` route authenticates the token through the identity provider named by the `identity`
block in `config.yaml` (see `lambda_ws_connection_handler.py`, which is one line), and keys the
connection by the principal's subject so replies route back to the right client.

- The block selects the `static` provider with one credential mapped to the principal `demo-user`.
- The credential's value is not in the file: the key `DEMO_AUTH_TOKEN` names a secret the secret
  capability resolves at startup, and Terraform passes it to the connection-handler Lambda as an
  environment variable from `var.demo_auth_token`.
- A missing or refused token closes the connection before it opens.

### Example token

Connect with the `demo_auth_token` value the stack was deployed with:

```bash
wss://{websocket_api_endpoint_url}/{websocket_api_stage_name}?token=<the demo_auth_token value>
```

To validate real tokens, swap the provider for `oidc` (Auth0, Keycloak, Okta or any other OIDC
issuer), `cognito`, `entra` or `firebase`; [`../openai-auth`](../openai-auth/README.md) shows an
Auth0 block. No code changes: the handshake is the framework's.

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

