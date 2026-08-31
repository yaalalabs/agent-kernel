# Agent Kernel running OpenAI Agent SDK Agents on a REST API

This package contains a demo of Agent Kernel running agents built with OpenAI Agents SDK. Users
can interact with agents via the Agent Kernel REST API. The example also demonstrates how to add a custom route
to the Agent Kernel REST API. This allows the users to utilize existing REST server for their custom REST endpoint
creations.

Example also demonstrates how to optionally add a custom route and custom middleware (prehook) to manage additional
context passed to the agent.

Chat execution runs on Agent Kernel's **queue-mode pipeline**
([#495](https://github.com/yaalalabs/agent-kernel/issues/495)): every request flows

```
REST API (Request Handler) → Input Queue → Agent Runner → Output Queue → Response Handler
```

with the `in_memory` queue transport, so all five components run as threads in this one process:
no broker, no cloud services. You get per-session FIFO ordering (parallel sessions across
`no_of_consumers` worker threads), bounded retry with a permanent-failure path, and request
deduplication: the same semantics as the production broker transports, minus durability. The
same application code scales out by switching `execution.queues.type` to a broker transport
(`sqs`, `kafka`, or `nats`): the agent runner then moves to its own container with no
code changes. See the comments in [config.yaml](config.yaml) for the knobs.

## Setup

Install dependencies using:

    ./build.sh

Install local dependencies in development mode using:

    ./build.sh local

Run REST API:

    export OPENAI_API_KEY=sk-...
    uv run app.py

On startup you'll see the pipeline boot:

```
ak.api.http - INFO - in_memory queue transport resolved: starting the single-process pipeline topology
ak.pipeline.io_handler - INFO - IOHandler starting: mode=rest_sync, transport=in_memory, topology=single-process
```

## 1. Synchronous REST (`mode: rest_sync`, the default)

The request is enqueued; the caller waits until the reply lands in the response store.

```bash
curl -s -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"prompt": "What is 2+2?", "agent": "general", "session_id": "s1"}'
# {"result": "4", "session_id": "s1"}
```

Requests in the same `session_id` are processed strictly in order and share conversation memory;
different sessions run in parallel.

## 2. Asynchronous REST (`mode: rest_async`)

Accept-then-poll: previously only available on the AWS ECS deployment, now identical locally.

```bash
AK_EXECUTION__MODE=rest_async uv run app.py
```

```bash
curl -s -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"prompt": "What is 2+2?", "agent": "general", "session_id": "s2"}'
# {"status": "ACCEPTED", "request_id": "<id>", "session_id": "s2"}

curl -s "http://localhost:8000/api/v1/chat?request_id=<id>&session_id=s2"
# {"result": "4", "session_id": "s2"}     (a second poll returns 404: replies are read once)
```

## 3. Token streaming over SSE (`mode: stream`)

Each token is fanned out as its own output-queue message and bridged to the open SSE response.

```bash
AK_EXECUTION__MODE=stream uv run app.py
```

```bash
curl -s -N -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Count from 1 to 5.", "agent": "general", "session_id": "s3"}'
# data: {"event": {"type": "message_start", "message_id": "m1", "role": "assistant"}, "done": false, "session_id": "s3"}
# data: {"delta": "1", "event": {"type": "text_delta", "message_id": "m1", "content": "1"}, "done": false, "session_id": "s3"}
# ...
# data: {"event": {"type": "message_end", "message_id": "m1"}, "done": false, "session_id": "s3"}
# data: {"done": true, "session_id": "s3"}
```

## Tests

    uv run pytest -s
