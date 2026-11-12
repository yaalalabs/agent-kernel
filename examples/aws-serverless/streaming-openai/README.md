## AWS Serverless WebSocket Streaming + OpenAI Example

This example deploys **Agent Kernel** on AWS using the `yaalalabs/ak-serverless/aws` Terraform module with **event streaming over WebSocket**.

Instead of buffering the full agent response and sending it once (`async` with the default `complete` message type), `async` + `delta` forwards each stream event as a separate `STREAM_CHUNK` message through the WebSocket connection as soon as it is produced.

The deployment exposes:

- WebSocket routes registered in `lambda_request_handler.py` (for example `app` and `app_info`)
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

- `agentkernel[aws,openai,redis]>=0.8.1`

### Agent Kernel runtime config

`config.yaml` is bundled into each Lambda package/image. The critical setting is:

```yaml
execution:
  mode: async
  message_type: delta
```

This tells Agent Kernel to dispatch to `ServerlessStreamAgentRunner` and instructs the response handler to broadcast each chunk individually rather than storing a single final response.

Update the Redis URL to point at your cluster endpoint.

### Terraform variables

Terraform variables are declared in `deploy/variables.tf`:

- `region`
- `prefix`
- `is_production`
- `openai_api_key` (sensitive)
- `demo_auth_token` (sensitive; the credential the `$connect` handshake accepts, see [Using the WebSocket API](#using-the-websocket-api))

Provide values via `terraform.tfvars` (recommended) or via `-var` flags.

## Deploy

1. Ensure dependencies are installed (`uv sync --all-extras` or run `./build.sh`).

2. From `examples/aws-serverless/streaming-openai/deploy/` run:

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
wss://{websocket_api_endpoint_url}/{websocket_api_stage_name}?token=<credential>
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

### Receiving stream chunks

After connecting and sending a chat message, you will receive a sequence of WebSocket messages:

```json
{"type": "STREAM_CHUNK", "event": {"type": "message_start", "message_id": "m1", "role": "assistant"}, "done": false, "session_id": "user-1"}
{"type": "STREAM_CHUNK", "delta": "Hello", "event": {"type": "text_delta", "message_id": "m1", "content": "Hello"}, "done": false, "session_id": "user-1"}
{"type": "STREAM_CHUNK", "delta": " world", "event": {"type": "text_delta", "message_id": "m1", "content": " world"}, "done": false, "session_id": "user-1"}
{"type": "STREAM_CHUNK", "event": {"type": "message_end", "message_id": "m1"}, "done": false, "session_id": "user-1"}
{"type": "STREAM_CHUNK", "done": true, "session_id": "user-1"}
```

Reassemble the `delta` fields in order to build the full response, testing for the key rather than assuming it: every chunk carries `event`, but `delta` appears only on a `text_delta`, so the `message_start` / `message_end` frames above carry no `delta` at all. The chunk with `"done": true` signals the end of the stream, and `session_id` identifies the conversation the stream belongs to.

## Custom WebSocket routes

The request handler registers two example routes:

- `app`
- `app_info`

## Cleanup

From `examples/aws-serverless/streaming-openai/deploy/` run:

```bash
terraform destroy
```
