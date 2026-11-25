# Open Agent Kernel running OpenAI Agents SDK based agents in AWS ECS over SSE (queue mode, streaming)

This package demonstrates Open Agent Kernel's queue-based, scalable containerized architecture
streaming over **plain HTTP with `rest_sync` + `delta`** — the agent's reply arrives as
`text/event-stream` on the ordinary chat route, token by token, with no WebSocket connection and no
client library.

Earlier releases fronted the ECS ingress service with an API Gateway HTTP API, which buffers a whole
response before sending any of it, so `terraform plan` rejected these settings outright. The gateway
is now a REST API with `responseTransferMode: STREAM`, which forwards partial responses as they
arrive.

Related examples:

- `openai-dynamodb-scalable` (queue mode, `rest_sync` + `complete`) — the same two-service
  architecture delivering one JSON reply instead of a stream. Start there if you don't need
  streaming
- `openai-stream-queue-mode` (queue mode, `async` + `delta`) — streams the same chunks over a
  WebSocket instead. Prefer it when clients are long-lived and bidirectional
- `openai-stream` (non-queue, `async` + `delta`) — single ECS service, no Agent Runner to scale

## Why Redis is mandatory here

The Agent Runner never answers the client. It fans each chunk onto the Output Queue, the IO
container's `ResponseHandler` writes them to the **response store**, and the chat route reads them
back out of that store to build the SSE frames. So the store has to support chunk streaming:

- **Redis or Valkey** — supported
- **DynamoDB** — cannot stream chunks. `terraform plan` warns, and `IOHandler` then refuses to start

This example points `execution.response_store.redis.url` in `config.yaml` at the long-lived shared
examples cluster in the base VPC, the same one every other CI-tested example uses, and so sets
`create_redis_cluster = false`. `terraform plan` warns that SSE needs a streaming store and sees no
module cluster; **that warning is expected here** — the external URL is what satisfies the
requirement, and Terraform cannot see it because it lives in `config.yaml`.

To provision a cluster per deployment instead, set `create_redis_cluster = true` and drop the `url`
line: Terraform then injects `AK_EXECUTION__RESPONSE_STORE__REDIS__URL` for you.

## Architecture Overview

- **REST/IO Service ECS Task** (`app_rest_service.py`, `IOHandler.run()`):
  - Thread 1: serves `POST /api/v1/chat`, enqueues the request to the Input Queue, then holds the
    response open and streams chunks out of the response store as they appear (never runs the agent)
  - Thread 2 (`ResponseHandler`): polls the Output Queue and writes each chunk to the response store
- **Agent Runner ECS Task** (`app_agent_runner.py`, `AgentRunner` → `StreamAgentRunner`): polls the
  Input Queue, streams the agent's reply, and sends **each chunk** as a separate message to the
  Output Queue. Scales on SQS backlog per task, independently of the REST/IO service
- **SQS Queues**: FIFO input and output queues
- **Redis (ElastiCache)**: the response store the SSE route reads from
- **DynamoDB**: session memory table
- **REST API Gateway + ALB**: proxies the chat route to the REST/IO service over VPC Link V2,
  reaching the ALB directly, with `responseTransferMode: STREAM` so chunks are not buffered

## The two timeouts

A stream is bounded by two independent caps, and raising one does not extend what the other is
cutting. Both are set to `900` in `deploy/main.tf`:

| Variable | Bounds | Symptom when it fires |
|---|---|---|
| `alb_idle_timeout` | a **silent gap** with no bytes in either direction | a stream that pauses mid-reply is dropped during the pause |
| `gateway_integration_timeout` | the **total** length of one integration request | a stream emitting steadily is cut at the limit, having never been idle |

Leaving `gateway_integration_timeout` unset is the trap: API Gateway's default is 29 seconds, so
every stream would die at 29 seconds and look exactly like the old buffering bug.

## Prerequisites

- AWS CLI configured with appropriate credentials
- Terraform (`1.9.5` or higher) installed
- Docker installed (for building container images)
- UV package manager installed

## Deployment Steps

1. Store the OpenAI API key in SSM Parameter Store (`<prefix>` is `prefix` in `deploy/terraform.tfvars`) and configure the deployment:
    ```bash
    aws ssm put-parameter --name "/ak/<prefix>/openai_api_key" \
        --type SecureString --value "$OPENAI_API_KEY" --overwrite
    export TF_VAR_vpc_id=<VPC_ID>
    export TF_VAR_private_subnet_ids='["subnet-xxx","subnet-yyy"]'
    ```
    The deployment sets `ssm_enabled = true` and `config.yaml` selects the `aws_ssm` secret provider, so the app reads the key from SSM at startup; no secret passes through Terraform.

2. **Point the example at the local module.** `deploy/main.tf` pins the published module
   (`yaalalabs/ak-containerized/aws` `0.10.2`), which predates the streaming REST gateway and has
   neither `alb_idle_timeout` nor `gateway_integration_timeout`, so a plain `terraform init` against
   it fails on unknown variables. Rewrite the source to this repo's copy:
    ```bash
    python3 scripts/deploy/inject_dependencies.py            # --revert to put the registry source back
    ```
    Skip this step only once a release containing the streaming REST gateway is published and the pin is raised to it.

3. Update `deploy/terraform.tfvars` if you want different naming (`prefix`, `region`).

4. Build and deploy from the `deploy/` directory:
    ```bash
    cd deploy && ./deploy.sh          # ./deploy.sh local for a locally built agentkernel wheel
    ```

    This builds **two** separate Docker images — `dist-rest-service/` (`app_rest_service.py`) and
    `dist-agent-runner/` (`app_agent_runner.py`) — then runs `terraform apply`.

    The first apply shows the API Gateway deployment as `(known after apply)`: the OpenAPI body
    embeds the ALB DNS name and the VPC link id. Later plans are stable.

5. Take the `agent_invoke_url` output and stream a reply:
    ```bash
    curl -N -X POST "$(terraform output -raw agent_invoke_url)" \
      -H 'Content-Type: application/json' \
      -d '{"session_id":"demo-1","prompt":"Explain the tank-and-canal irrigation of ancient Anuradhapura and Polonnaruwa in detail."}' \
      | python3 -u -c 'import sys,time
start=None
for line in sys.stdin:
    now=time.monotonic()
    start = now if start is None else start
    print(f"+{now-start:6.2f}s  {line.rstrip()}", flush=True)'
    ```

    `-N` disables curl's own buffering; without it you cannot tell a streamed reply from a buffered
    one. The elapsed offsets are the actual test. (`date +%N` is deliberately avoided: it is a GNU
    extension and prints literally on macOS, which would silently flatten every timestamp.)

## Reading the result

- **Pass**: timestamps spread across several seconds, one `data:` frame per token or small group.
- **Fail**: every frame carries the same timestamp — the reply was buffered somewhere and released
  in one burst.

Ask a question long enough to take several seconds to answer. A one-line reply arrives instantly
whether it streamed or not, and proves nothing either way.

If it arrives in one burst, the gateway is not necessarily the culprit. Curl the ALB directly from
inside the VPC, using the `alb_dns_name` output, to take API Gateway out of the picture. If that
bursts too, the buffering is in the client, the agent, or the response store, and the gateway is not
the component under test.

## Cleanup

From `examples/aws-containerized/openai-sse-queue-mode/deploy/` run:

```bash
terraform destroy
```
