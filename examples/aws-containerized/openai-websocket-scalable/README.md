# Agent Kernel running OpenAI Agents SDK based agents in AWS ECS over WebSocket (queue mode, scalable)

This package demonstrates Agent Kernel's queue-based, scalable containerized architecture
exposed over a **WebSocket API**, combining:

- `openai-websocket` (direct WebSocket mode) — see that example for the auth/wire-protocol basics
- `openai-dynamodb-scalable` (queue-based REST mode) — see that example for the two-image /
  autoscaling pattern

Instead of running the agent inline in the ingress container, chat frames are enqueued to SQS and
processed by a separately-scalable Agent Runner service — so a burst of WebSocket traffic scales
the agent workers independently of the number of open connections.

## Architecture Overview

- **REST/IO Service ECS Task** (`app_rest_service.py`, started via `ECSIOHandler.run()`):
  - Thread 1: authenticates `$connect`, on the `chat` route enqueues the request to the Input
    Queue (never runs the agent itself), and answers the custom `echo` route directly (registered
    via `@AWSWebsocketAPI.register("echo")`)
  - Thread 2 (`ECSOutputConsumer`): polls the Output Queue and pushes each chat reply back over
    the originating WebSocket connection
- **Agent Runner ECS Task** (`app_agent_runner.py`, `ECSAgentRunner`): polls the Input Queue, runs
  the agent, and sends the result — with the `endpoint_url` forwarded — to the Output Queue.
  Scales on SQS backlog per task, independently of the REST/IO service.
- **SQS Queues**: FIFO input and output queues
- **DynamoDB**: session memory table + WebSocket `user_id` <-> `connection_id` connections table
- **WebSocket API Gateway + ALB**: routes `$connect` / `$disconnect` / `chat` / `echo` /
  `$default` to the REST/IO service via VPC Link

```
Client --(wss, ?token=...)--> WS API Gateway --> REST/IO service ($connect / enqueue chat)
                                                        |
                                                        v
                                                  Input SQS Queue
                                                        |
                                                        v
                                              Agent Runner (scales on backlog)
                                                        |
                                                        v
                                                 Output SQS Queue
                                                        |
                                                        v
                                     REST/IO service's output-queue consumer
                                                        |
                                                        v
                                     pushed back over the WebSocket connection
```

## WebSocket wire protocol

Same as `openai-websocket`. Connect with `wss://<endpoint>/<stage>?token=<jwt>`, then send:

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
request was queued — the actual agent reply arrives later as a separate push:

```json
{
  "type": "CHAT_RESPONSE",
  "status": "SUCCESS",
  ...
}
```

## Custom Routes

Beyond the built-in `chat` route, `app_rest_service.py` registers a custom `echo` route with the
`@AWSWebsocketAPI.register("echo")` decorator — route name only (the method is always POST and
the path is always `/ws/echo`). The decorated function receives a plain `dict` — `{"message": ...,
"user_id": ...}` — not the connection id or push endpoint, and returns a `dict`, which the framework
broadcasts to the client:

```python
from agentkernel.aws import AWSWebsocketAPI

@AWSWebsocketAPI.register("echo")
async def echo(ctx: dict) -> dict:
    return ctx
```

The route is also declared in Terraform via `ws_routes` (`deploy/main.tf`), which must agree with
the route name registered in code — Python cannot create the API Gateway integration, so both
sides declare the route (exactly like the configurable `chat` route).

Unlike `chat`, `echo` is answered directly by the REST/IO service — it doesn't enqueue to the
Input Queue or involve the Agent Runner, since it doesn't need agent processing.

Send:

```json
{
  "route": "echo",
  "body": {
    "prompt": "hello there"
  }
}
```

Receive (pushed back over the connection as a `SYSTEM_RESPONSE`, no queue round trip):

```json
{
  "type": "SYSTEM_RESPONSE",
  "message": {
    "route": "echo",
    "body": { "prompt": "hello there" }
  },
  "user_id": "user-1"
}
```

The framework resolves the authenticated user internally, broadcasts the returned `dict`, builds
the HTTP response envelope, and handles errors — a registered route only implements its own logic.
Return `None` to broadcast nothing. Any exception raised by the route is logged, an error is
broadcast to the client, and a 500 is returned.

Because routes are registered globally (before `run()` is called), `main()` calls
`ECSIOHandler.run(auth_validator=CustomAuthValidator())` directly — the framework-managed handler
picks up the registered `echo` route automatically, so no custom handler injection or manual
`ThreadRunner` wiring is needed.

## Auth

`app_rest_service.py` defines the same demo `CustomAuthValidator` as `openai-websocket`: it
decodes an **unsigned** JWT and accepts it when `userId` is one of `user-1`/`user-2` and the
matching `email` is `test1@test.com`/`test2@test.com`.

**Warning:** signature verification is disabled for demo purposes only. Use real JWT verification
(or your own `AuthValidator`) in production.

## Execution mode

`config.yaml` sets `execution.mode: async` — the full agent reply is pushed back as one
`CHAT_RESPONSE` message. See [`openai-stream`](../openai-stream) — the same
architecture with `execution.mode: stream` instead, which delivers the reply token-by-token as a
sequence of `STREAM_CHUNK` messages.

There is no REST response store in WebSocket modes — replies are always pushed over the
connection, never polled.

## Agent Runner Auto Scaling

Enabled in `deploy/main.tf` via `scaling_config`, identical mechanism to
`openai-dynamodb-scalable`: a target-tracking policy scales the Agent Runner service on
`BacklogPerTask` (queue depth / running tasks). See the [containerized deployment
README](../../../ak-deployment/ak-aws/containerized/README.md#agent-runner-autoscaling) for
details on tuning `backlog_target` and cooldowns.

## Prerequisites

- AWS CLI configured with appropriate credentials
- Terraform (`1.9.5` or higher) installed
- Docker installed (for building container images)
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

3. Build and deploy from the `deploy/` directory:
    ```bash
    cd deploy && ./deploy.sh          # ./deploy.sh local for a locally built agentkernel wheel
    ```

    This builds **two** separate Docker images — `dist-rest-service/` (`app_rest_service.py`) and
    `dist-agent-runner/` (`app_agent_runner.py`) — then runs `terraform apply`.

4. Note the `websocket_api_endpoint_url` and `websocket_api_stage_name` outputs, then connect to
   `wss://<websocket_api_endpoint_url>/<websocket_api_stage_name>?token=<jwt>` with a WebSocket
   client of your choice and send frames per the wire protocol above.

## Cleanup

From `examples/aws-containerized/openai-websocket-scalable/deploy/` run:

```bash
terraform destroy
```
