# Agent Kernel running OpenAI Agents SDK based agents in AWS ECS over WebSocket (no queue, streaming)

This package demonstrates Agent Kernel running agents built with the OpenAI Agents SDK, deployed
on AWS ECS and exposed over a **WebSocket API in direct (non-queue), STREAM execution mode** —
the agent runs inline in the same container that handles the WebSocket connection, and its reply
is delivered token-by-token as a sequence of `STREAM_CHUNK` messages instead of one final
`CHAT_RESPONSE`.

- `openai-websocket` (direct WebSocket mode, `async`) — see that example for the auth/wire-protocol
  basics of non-streaming direct mode; this one is identical except for `execution.mode` and the
  streamed reply
- `openai-stream-queue-mode` (queue-based WebSocket mode, `stream`) — see that example if you need the Agent
  Runner to scale independently of ingress; this one trades that horizontal scalability for lower
  latency and a single container to operate

Unlike the queue-based streaming example, there is only **one** ECS service here. The container:

- authenticates the WebSocket `$connect` handshake,
- runs the agent **inline** when a `chat` frame arrives (no SQS, no separate Agent Runner
  service), and
- pushes each token delta straight back over the same connection as its own `STREAM_CHUNK`
  message, terminated by a chunk with `"done": true`.

No application code changes are needed to go from `async` to `stream` in direct mode — `app.py` is
identical to `openai-websocket`'s; only `config.yaml` (`execution.mode: stream`) and
`deploy/main.tf` (`execution_mode = "stream"`) differ.

## Deployed Resources

- ECS Fargate service running the containerized application (the framework-managed WebSocket
  handler, carrying the built-in `chat` route plus the custom `status` and `echo` routes
  registered in `app.py`)
- WebSocket API Gateway (`$connect` / `$disconnect` / `chat` / `status` / `echo` / `$default`
  routes), proxied to the ECS service via VPC Link + ALB
- DynamoDB table mapping `user_id` <-> `connection_id` (managed by the Terraform module)
- DynamoDB table for agent memory (session store)

## How it works

1. A client opens a WebSocket connection with an auth token in the query string:
   `wss://<endpoint>/<stage>?token=<jwt>`.
2. API Gateway routes `$connect` to the container, which calls `CustomAuthValidator.validate()`
   (see `app.py`). A non-2xx response rejects the connection.
3. The client sends a JSON frame on the `chat` route (see below). The container runs the agent
   inline via `ChatService.process_stream_chat_async` and pushes one `STREAM_CHUNK` message per
   token delta back over the same connection, followed by a final chunk with `"done": true`.
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

The chat frame's own HTTP response (from the WS API Gateway integration) just confirms the
request was accepted — the reply arrives over the connection as a **sequence** of pushes, one per
token delta, terminated by a chunk with `"done": true`:

```json
{"type": "STREAM_CHUNK", "event": {"type": "message_start", "message_id": "m1", "role": "assistant"}, "session_id": "..."}
{"type": "STREAM_CHUNK", "delta": "Australia", "event": {"type": "text_delta", "message_id": "m1", "content": "Australia"}, "session_id": "..."}
...
{"type": "STREAM_CHUNK", "delta": " Cup.", "event": {"type": "text_delta", "message_id": "m1", "content": " Cup."}, "session_id": "..."}
{"type": "STREAM_CHUNK", "event": {"type": "message_end", "message_id": "m1"}, "session_id": "..."}
{"type": "STREAM_CHUNK", "done": true, "session_id": "..."}
```

A client should append `delta` values in the order received until it sees `"done": true`. If the
agent run fails, a single chunk with `"error": "<message>"` and `"done": true` is pushed instead —
there is no partial `error` + separate `done` chunk.

## Custom Routes

Beyond the built-in `chat` route, `app.py` registers two custom routes with the
`@AWSWebsocketAPI.register(...)` decorator — route name only (the method is always POST and the
path is always `/ws/<route>`). These are unaffected by `execution.mode`: they always broadcast a
single `SYSTEM_RESPONSE`, streaming only applies to the `chat` route.

```python
from agentkernel.aws import AWSWebsocketAPI

@AWSWebsocketAPI.register("status")
async def status(ctx: dict) -> dict:
    return {"status": "OK", "user_id": ctx["user_id"]}
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
  "user_id": "user-1"
}
```

The second custom route, `echo`, reads the frame's raw JSON body — no `BaseRequest`/`BaseRunRequest`
schema is imposed on custom routes — and returns it unchanged:

```python
@AWSWebsocketAPI.register("echo")
async def echo(ctx: dict) -> dict:
    return ctx
```

## Auth

`app.py` defines a demo `CustomAuthValidator` that decodes an **unsigned** JWT and accepts it when
`userId` is one of `user-1`/`user-2` and the matching `email` is `test1@test.com`/`test2@test.com`.
`userId` is required — it's how the container maps a connection to a user so replies can be routed
back to the right client.

**Warning:** signature verification is disabled for demo purposes only. Use real JWT verification
(or your own `AuthValidator`) in production.

## Execution mode

`config.yaml` sets `execution.mode: stream`. There is no REST response store in WebSocket modes —
replies are always pushed over the connection, never polled. Setting it back to `async` delivers
the full agent reply as one `CHAT_RESPONSE` message instead — see [`openai-websocket`](../openai-websocket).

## Prerequisites

- AWS CLI configured with appropriate credentials
- Terraform (`1.9.5` or higher) installed
- Docker installed (for building the container image)
- UV package manager installed

## Deployment Steps

1. Configure environment variables:
    ```bash
    export TF_VAR_openai_api_key=<OPENAI_API_KEY>
    export TF_VAR_vpc_id=<VPC_ID>
    export TF_VAR_private_subnet_ids='["subnet-xxx","subnet-yyy"]'
    ```

2. Update `deploy/terraform.tfvars` if you want different naming (`product_alias`, `env_alias`,
   `module_name`, `region`).

3. Run the deployment script from the `deploy/` directory:
    ```bash
    cd deploy && ./deploy.sh  # ./deploy.sh local for local agentkernel build
    ```

    The script builds the application deployment package with dependencies, then runs
    `terraform apply`. The module builds the Docker image from `../dist` and pushes it to a
    Terraform-managed ECR repository automatically — no manual ECR setup or push is needed.

4. Note the `websocket_api_endpoint_url` and `websocket_api_stage_name` outputs, then connect to
   `wss://<websocket_api_endpoint_url>/<websocket_api_stage_name>?token=<jwt>` with a WebSocket
   client of your choice and send frames per the wire protocol above.

## Cleanup

From `examples/aws-containerized/openai-stream/deploy/` run:

```bash
terraform destroy
```
