## AWS Serverless WebSocket Streaming + OpenAI Example

This example deploys **Agent Kernel** on AWS using the `yaalalabs/ak-serverless/aws` Terraform module with **token-level streaming over WebSocket**.

Instead of buffering the full agent response and sending it once (async mode), stream mode forwards each generated token as a separate `STREAM_CHUNK` message through the WebSocket connection as soon as it is produced.

The deployment exposes:

- A REST API (custom endpoints: `/api/app`, `/api/app_info`)
- A WebSocket API (connect/disconnect handled by `lambda_ws_connection_handler.py`)
- A streaming pipeline: request handler → input SQS → agent runner (streams chunks) → output SQS → response handler (broadcasts each chunk via WebSocket)

## How streaming works

1. Client connects to the WebSocket API and sends a `chat` message.
2. The request handler enqueues it to the input SQS queue.
3. The agent runner (`ServerlessStreamAgentRunner`) consumes the message, calls the agent, and sends **each streamed token chunk** as a separate message to the output SQS queue.
4. The response handler (`ResponseHandler`) consumes each chunk and broadcasts it to the connected WebSocket client wrapped in a `{"type": "STREAM_CHUNK", ...}` envelope.
5. The client receives chunks in real time and reassembles the response. The final chunk has `"done": true`.

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

- `agentkernel[aws,openai,redis]>=0.5.1`

### Agent Kernel runtime config

`config.yaml` is bundled into each Lambda package/image. The critical setting is:

```yaml
execution:
  mode: stream
```

This tells Agent Kernel to use `ServerlessStreamAgentRunner` (selected automatically at import time) and instructs the response handler to broadcast each chunk individually rather than storing a single final response.

Update the Redis URL to point at your cluster endpoint.

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

1. Ensure dependencies are installed (`uv sync --all-extras` or run `./build.sh`).

2. From `examples/aws-serverless/websocket-streaming-openai/deploy/` run:

```bash
./deploy.sh
```

This script:

- Builds Zip packages for request/response/ws-connection handlers
- Builds the container image context for the agent runner
- Runs `terraform init` and `terraform apply`

For local development with a locally built `agentkernel` wheel:

```bash
./deploy.sh local
```

## Outputs

After apply, Terraform outputs:

- `websocket_api_endpoint_url`
- `websocket_api_stage_name`

See `deploy/outputs.tf`.

## Using the WebSocket API

Connect to the WebSocket API by combining the Terraform outputs:

```bash
wss://{websocket_api_endpoint_url}/{websocket_api_stage_name}?token=your-jwt-token
```

The `$connect` route validates the JWT token via `CustomAuthTokenValidator` in `lambda_ws_connection_handler.py`.

- The validator decodes a JWT (signature verification is disabled in this example).
- The connection is allowed only if the JWT payload contains `userId: "user-1"` and `email: "test@test.com"`.

### Example token

Any JWT-formatted token with `userId: "user-1"` and `email: "test@test.com"` claims will pass validation.

### Receiving stream chunks

After connecting and sending a chat message, you will receive a sequence of WebSocket messages:

```json
{"type": "STREAM_CHUNK", "chunk": "Hello", "done": false}
{"type": "STREAM_CHUNK", "chunk": " world", "done": false}
{"type": "STREAM_CHUNK", "chunk": "!", "done": true}
```

Reassemble the `chunk` fields in order to build the full response. The chunk with `"done": true` signals the end of the stream.

## Custom REST endpoints

The request handler registers two example endpoints:

- `GET /api/app`
- `POST /api/app_info`

## Cleanup

From `examples/aws-serverless/websocket-streaming-openai/deploy/` run:

```bash
terraform destroy
```
