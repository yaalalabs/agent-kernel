# Agent Kernel running OpenAI Agents SDK based agents in AWS ECS over WebSocket (no queue)

This package contains a demo of Agent Kernel running agents built with the OpenAI Agents SDK,
deployed on AWS ECS and exposed over a **WebSocket API in direct (non-queue) mode**.

Unlike the queue-based containerized examples (`openai-dynamodb-scalable`), there is only **one**
ECS service here. The REST service container:

- authenticates the WebSocket `$connect` handshake,
- runs the agent **inline** when a chat message arrives (no SQS, no separate Agent Runner
  service), and
- pushes the reply straight back over the same connection.

This is the simplest way to get a WebSocket-based chat experience — trade the horizontal
scalability of queue mode for lower latency and a single container to operate. See
`openai-dynamodb-scalable` if you need the agent runner to scale independently of ingress.

## Deployed Resources

- ECS Fargate service running the containerized application (the framework-managed WebSocket
  handler, carrying the built-in `chat` route plus the custom `status` and `echo` routes
  registered in `app.py`)
- WebSocket API Gateway (`$connect` / `$disconnect` / `chat` / `status` / `echo` / `$default`
  routes), proxied to the ECS service via VPC Link + ALB
- DynamoDB connections table: one row per connection, keyed by the principal's subject (`user_id`) with the
  principal stored beside it (managed by the Terraform module)
- DynamoDB table for agent memory (session store)

## How it works

1. A client opens a WebSocket connection with its credential in the query string:
   `wss://<endpoint>/<stage>?token=<credential>`.
2. API Gateway routes `$connect` to the container, which authenticates the token through the
   identity provider in `config.yaml` and stores the resulting principal against the connection.
   A non-2xx response rejects the connection.
3. The client sends a JSON frame on the `chat` route (see below). The container runs the agent
   inline via `ChatService` and pushes a `CHAT_RESPONSE` message back over the same connection.
4. On close, API Gateway routes `$disconnect` to the container, which removes the connection
   record.

### WebSocket wire protocol

Send (note the top-level `route` field — the WebSocket API's
`route_selection_expression` is `$request.body.route`):

```json
{
  "route": "chat",
  "body": {
    "session_id": "<any client-generated id>",
    "agent": "triage",
    "prompt": "Who won the 1996 cricket world cup?"
  }
}
```

Receive:

```json
{
  "type": "CHAT_RESPONSE",
  "status": "SUCCESS",
  ...
}
```

## Custom Routes

Beyond the built-in `chat` route, `app.py` registers two custom routes with the
`@AWSWebsocketAPI.register(...)` decorator — route name only (the method is always POST and the
path is always `/ws/<route>`). The decorated function receives a plain `dict`, `{"message": ...,
"principal": ...}` (the frame's body and the connection's `Principal`), not the connection id or push
endpoint, and returns a `dict`, which the framework broadcasts to the client:

```python
from agentkernel.aws import AWSWebsocketAPI

@AWSWebsocketAPI.register("status")
async def status(ctx: dict) -> dict:
    return {"status": "OK", "subject": ctx["principal"].subject}
```

The routes are also declared in Terraform via `ws_routes` (`deploy/main.tf`), which must agree with
the route names registered in code — Python cannot create the API Gateway integration, so both
sides declare the route (exactly like the configurable `chat` route).

Send:

```json
{
  "route": "status",
  "body": {}
}
```

Receive (pushed back over the connection as a `SYSTEM_RESPONSE`):

```json
{
  "type": "SYSTEM_RESPONSE",
  "status": "OK",
  "subject": "demo-user"
}
```

### Reading the request body

`status` ignores the frame's payload. The second custom route, `echo`, reads it — `ctx["message"]`
is the frame's raw JSON body, exactly as the client sent it: no `BaseRequest`/`BaseRunRequest` schema
is imposed on custom routes, so `echo` simply hands the context back, the frame's body as it arrived
and the connection's principal as JSON:

```python
@AWSWebsocketAPI.register("echo")
async def echo(ctx: dict) -> dict:
    return ctx
```

Send:

```json
{
  "route": "echo",
  "body": {
    "prompt": "hello there",
    "locale": "en-US"
  }
}
```

Receive:

```json
{
  "type": "SYSTEM_RESPONSE",
  "message": {
    "route": "echo",
    "body": { "prompt": "hello there", "locale": "en-US" }
  },
  "principal": { "subject": "demo-user", "kind": "user", "provider": "static", "namespace": "static", "groups": [], "roles": [], "claims": {} }
}
```

Custom routes impose no schema on the frame's body — unlike `chat`, it is never validated as a
`BaseRunRequest`. `echo` reads `ctx` however it likes; a route can validate whatever shape it
expects (e.g. requiring `body.prompt`) and simply raise on failure.

The framework resolves the authenticated user internally, broadcasts the returned `dict`, builds
the HTTP response envelope, and handles errors — a registered route only implements its own logic.
Return `None` to broadcast nothing. Any exception raised by the route is logged, an error is
broadcast to the client, and a 500 is returned.

## Auth

The `$connect` handshake authenticates the `?token=` query parameter through the identity provider
named by the `identity` block in `config.yaml`, and the connection is keyed by the principal's
subject, which is how replies are routed back to the right client. The block here selects the
`static` provider with one credential mapped to the principal `demo-user`. The credential's value is
not in the file: the key `DEMO_AUTH_TOKEN` names a secret the secret capability resolves at startup,
and Terraform passes it to the container as an environment variable from `var.demo_auth_token`.
Connect with that value:

```
wss://<endpoint>/<stage>?token=<the demo_auth_token value>
```

A missing or refused token closes the connection before it opens. To validate real tokens, swap the
provider for `oidc` (Auth0, Keycloak, Okta or any other OIDC issuer), `cognito`, `entra` or
`firebase`; [`examples/aws-serverless/openai-auth`](../../aws-serverless/openai-auth/README.md)
shows an Auth0 block. No code changes: the handshake is the framework's.

## Execution mode

`config.yaml` sets `execution.mode: async`, meaning the full agent reply is sent as one
`CHAT_RESPONSE` message. Adding `execution.message_type: delta` delivers the reply token-by-token as a
sequence of `STREAM_CHUNK` messages, terminated by a chunk with `"done": true` — see
[`openai-stream`](../openai-stream) for the direct-mode streaming counterpart of this example, or
[`openai-stream-queue-mode`](../openai-stream-queue-mode) if you need the Agent Runner to scale
independently of ingress.
## Prerequisites

- AWS CLI configured with appropriate credentials
- Terraform (`1.9.5` or higher) installed
- Docker installed (for building the container image)
- UV package manager installed

## Deployment Steps

1. Configure environment variables:
    ```bash
    export TF_VAR_openai_api_key=<OPENAI_API_KEY>
    export TF_VAR_demo_auth_token=<any secret string: the token clients connect with>
    export TF_VAR_vpc_id=<VPC_ID>
    export TF_VAR_private_subnet_ids='["subnet-xxx","subnet-yyy"]'
    ```

2. Update `deploy/terraform.tfvars` if you want different naming (`prefix`, `region`).

3. Run the deployment script from the `deploy/` directory:
    ```bash
    cd deploy && ./deploy.sh  # ./deploy.sh local for local agentkernel build
    ```

    The script builds the application deployment package with dependencies, then runs
    `terraform apply`. The module builds the Docker image from `../dist` and pushes it to a
    Terraform-managed ECR repository automatically — no manual ECR setup or push is needed.

4. Note the `websocket_api_endpoint_url` and `websocket_api_stage_name` outputs, then connect to
   `wss://<websocket_api_endpoint_url>/<websocket_api_stage_name>?token=<credential>` with a WebSocket
   client of your choice and send frames per the wire protocol above.

## Cleanup

From `examples/aws-containerized/openai-websocket/deploy/` run:

```bash
terraform destroy
```
