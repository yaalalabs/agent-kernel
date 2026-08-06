# Agent Kernel running OpenAI Agents SDK based agents in AWS ECS over WebSocket (queue mode, streaming)

This package demonstrates Agent Kernel's queue-based, scalable containerized architecture
exposed over a **WebSocket API in STREAM execution mode** — the agent's reply is delivered
token-by-token as a sequence of `STREAM_CHUNK` messages instead of one final `CHAT_RESPONSE`.

- `openai-websocket` (direct WebSocket mode, `async`) — see that example for the auth/wire-protocol
  basics of non-streaming WebSocket mode
- `openai-stream` (direct WebSocket mode, `stream`) — see that example if you don't need
  the Agent Runner to scale independently of ingress; same wire protocol, single ECS service
- `openai-websocket-scalable` (queue-based WebSocket mode, `async`) — see that example for the
  two-image / autoscaling pattern this one reuses unchanged

Chat frames are enqueued to SQS and processed by a separately-scalable Agent Runner service, same
as `openai-websocket-scalable` — the only difference is `execution.mode: stream` in `config.yaml`
(and `execution_mode = "stream"` in `deploy/main.tf`): the agent's reply is delivered as a sequence
of `STREAM_CHUNK` messages, one per token delta, instead of a single `CHAT_RESPONSE` once the
agent finishes.

No application code changes are needed to go from `async` to `stream` — both `app_rest_service.py`
and `app_agent_runner.py` are identical apart from the custom echo route (`openai-websocket-scalable`'s
`app_rest_service.py` registers one via `@AWSWebsocketAPI.register`; this one registers none); only
`config.yaml` and `deploy/main.tf` differ.

## Architecture Overview

- **REST/IO Service ECS Task** (`app_rest_service.py`, started via `ECSIOHandler.run()`):
  - Thread 1: authenticates `$connect`, and on the `chat` route enqueues the request to the Input
    Queue (never runs the agent itself)
  - Thread 2 (`ECSOutputConsumer`): polls the Output Queue and pushes each streamed chunk back
    over the originating WebSocket connection as it arrives
- **Agent Runner ECS Task** (`app_agent_runner.py`, `ECSAgentRunner` → `ECSStreamAgentRunner`):
  polls the Input Queue, streams the agent's reply, and sends **each chunk** — with the
  `endpoint_url` forwarded — as a separate message to the Output Queue. Scales on SQS backlog per
  task, independently of the REST/IO service.
- **SQS Queues**: FIFO input and output queues
- **DynamoDB**: session memory table + WebSocket `user_id` <-> `connection_id` connections table
- **WebSocket API Gateway + ALB**: routes `$connect` / `$disconnect` / `chat` / `$default` to the
  REST/IO service via VPC Link

```
Client --(wss, ?token=...)--> WS API Gateway --> REST/IO service ($connect / enqueue chat)
                                                        |
                                                        v
                                                  Input SQS Queue
                                                        |
                                                        v
                                    Agent Runner (ECSStreamAgentRunner, scales on backlog)
                                                        |
                                          one Output SQS message PER chunk
                                                        |
                                                        v
                                     REST/IO service's output-queue consumer
                                                        |
                                       one STREAM_CHUNK push PER chunk
                                                        v
                                          pushed back over the WebSocket connection
```

## WebSocket wire protocol

Connect with `wss://<endpoint>/<stage>?token=<jwt>`, then send:

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
request was queued — the reply arrives later as a **sequence** of pushes, one per token delta,
terminated by a chunk with `"done": true`:

```json
{"type": "STREAM_CHUNK", "delta": "Australia", "session_id": "..."}
{"type": "STREAM_CHUNK", "delta": " won", "session_id": "..."}
{"type": "STREAM_CHUNK", "delta": " the", "session_id": "..."}
{"type": "STREAM_CHUNK", "delta": " 1996", "session_id": "..."}
{"type": "STREAM_CHUNK", "delta": " Cricket", "session_id": "..."}
{"type": "STREAM_CHUNK", "delta": " World", "session_id": "..."}
{"type": "STREAM_CHUNK", "delta": " Cup.", "session_id": "..."}
{"type": "STREAM_CHUNK", "done": true, "session_id": "..."}
```

A client should append `delta` values in the order received (SQS FIFO ordering + `session_id` as
the message group id keeps chunks for one request in order) until it sees `"done": true`. If the
agent run fails, a single chunk with `"error": "<message>"` and `"done": true` is pushed instead —
there is no partial `error` + separate `done` chunk.

## Auth

`app_rest_service.py` defines the same demo `CustomAuthValidator` as `openai-websocket`: it
decodes an **unsigned** JWT and accepts it when `userId` is one of `user-1`/`user-2` and the
matching `email` is `test1@test.com`/`test2@test.com`.

**Warning:** signature verification is disabled for demo purposes only. Use real JWT verification
(or your own `AuthValidator`) in production.

## Execution mode

`config.yaml` sets `execution.mode: stream`. There is no REST response store in WebSocket
modes — replies are always pushed over the connection, never polled.

## Agent Runner Auto Scaling

Enabled in `deploy/main.tf` via `scaling_config`, identical mechanism to
`openai-websocket-scalable`: a target-tracking policy scales the Agent Runner service on
`BacklogPerTask` (queue depth / running tasks) — note that in STREAM mode the Output Queue sees
many more messages per request (one per chunk instead of one per reply), so size
`backlog_target`/queue throughput accordingly. See the [containerized deployment
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

From `examples/aws-containerized/openai-stream-queue-mode/deploy/` run:

```bash
terraform destroy
```
