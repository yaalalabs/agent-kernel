---
sidebar_position: 10
---

# Queue Mode Guide

This document explains the queue mode architecture for both Lambda (serverless) and
ECS (containerized) deployments.

---

## What Is Queue Mode?

Queue mode decouples the HTTP request from the agent processing by placing an SQS FIFO
queue between the caller and the Agent Runner. This gives you:

- **Backpressure control** – the queue absorbs burst traffic.
- **Ordered processing per session** – `MessageGroupId = SessionID` keeps chat turns in order.
- **Automatic retries** – failed messages reappear after the visibility timeout expires.
- **Deduplication** – `MessageDeduplicationId` prevents the same message being processed twice.

Two sub-modes are supported:

| Mode | What the caller does | How they get the response |
|------|---------------------|---------------------------|
| **REST Sync** | POST → wait | Same HTTP response (polls DB internally) |
| **REST Async** | POST → get a job ID | Later GET to a separate endpoint |

---

## How It Works in Lambda (Serverless)

### Components

```
Client
  │
  ▼
API Gateway (HTTP)
  │  POST /api/{version}/{endpoint}
  ▼
Request Handler Lambda
  │  puts message on Input Queue
  ▼
Input SQS FIFO Queue  ──────────────────────────────────────────────────────┐
  │  Event Source Mapping (batch = 1 per Lambda)                            │
  ▼                                                                          │
Agent Runner Lambda (scales 1:1 with queue batches)                         │ visibility
  │  processes message, puts result on Output Queue                         │ timeout
  ▼                                                                          │
Output SQS FIFO Queue ◄─────────────────────────────────────────────────────┘
  │  Event Source Mapping
  ▼
Response Handler Lambda
  │
  ├─► (REST Sync / REST Async / Streaming)  writes to DynamoDB Response Store
  │
  └─► (Async/WebSocket)  sends directly via WebSocket PostToConnection
```

### SQS Queue Design

Both queues are **FIFO** with:

| Setting | Purpose |
|---------|---------|
| `MessageGroupId = SessionID` | Preserves order within a session |
| `MessageDeduplicationId` | Prevents the agent running the same turn twice |
| `MessageVisibilityTimeout` | Makes undeleted messages reappear for retry |
| `MessageRetentionPeriod` | Auto-deletes stuck messages, breaks infinite loops |
| DLQ (optional) | Catches messages that exceed `maxReceiveCount` |

### REST Sync Flow

1. Client sends `POST /api/v1/chat`.
2. **Request Handler Lambda** puts the message on the Input Queue, then **polls DynamoDB**
   until the response appears, and returns it on the same HTTP connection.
3. **Agent Runner Lambda** is triggered by the Input Queue ESM, processes the message,
   puts the response on the Output Queue, and returns `batchItemFailures` for anything
   that failed (so those messages come back for retry).
4. **Response Handler Lambda** is triggered by the Output Queue ESM and writes the
   response to DynamoDB (keyed by SessionID, with a TTL).

Failure handling:
- If the Agent Runner Lambda crashes, the message reappears after the visibility timeout.
- Partial failures are reported via `batchItemFailures`; only those messages stay in the
  queue for retry.
- If the Response Handler fails to write DynamoDB, the message stays on the Output Queue
  and is retried.

### REST Async Flow

Same as REST Sync except:

1. The `POST` returns immediately (202) with the session/job ID.
2. The client polls `GET /api/v1/chat/{sessionId}` to retrieve the result.
3. The Request Handler uses **separate routes** for the POST and GET.

### WebSocket (Async) Mode

1. Client connects via WebSocket (API Gateway WebSocket).
2. **WS Connection Handler Lambda** stores the connection ID in DynamoDB.
3. Messages are put on the Input Queue (same Agent Runner pipeline).
4. **Response Handler Lambda** reads from the Output Queue and calls
   `execute-api:ManageConnections` (PostToConnection) to push the response back to the
   client over the still-open WebSocket.

### Terraform Modules (Serverless)

Located under `ak-deployment/ak-aws/serverless/modules/`:

| Module | Role |
|--------|------|
| `queues/` | Creates Input and Output SQS FIFO queues |
| `request-handler/` | Request Handler Lambda + optional SQS send permission |
| `agent-runner/` | Agent Runner Lambda + ESM binding to Input Queue |
| `response-handler/` | Response Handler Lambda + ESM binding to Output Queue |
| `api-gateway/` | HTTP API Gateway wiring |
| `websocket-api-gateway/` | WebSocket API Gateway |
| `ws-connection-handler/` | WebSocket connection lifecycle Lambda |

---

## How Queue Mode Works in ECS (Containerized)

The ECS deployment uses the same pipeline as Lambda, **except Lambda functions are
replaced by long-running ECS services**. The IO container runs two threads via
`ThreadRunner`; the Agent Runner is a separate ECS service that extends `ECSSQSConsumer`.

### Python Class Hierarchy

| Class | Container | Role |
|-------|-----------|------|
| `ECSIOHandler` | IO container | Entrypoint: starts Thread 1 + Thread 2 via `ThreadRunner` |
| `ECSQueueRequestHandler` | IO container / Thread 1 | FastAPI: `POST /api/v1/chat` enqueues; `GET /api/v1/chat/{id}` polls |
| `ECSOutputConsumer` | IO container / Thread 2 | Extends `ECSSQSConsumer` — polls Output Queue → DynamoDB / WebSocket |
| `ECSAgentRunner` | Agent Runner container | Extends `ECSSQSConsumer` — polls Input Queue, runs agent, sends to Output Queue |
| `ECSSQSConsumer` | both | Abstract base: SQS long-poll loop, retry/permanent-failure logic |
| `ThreadRunner` | IO container | Runs N callables as peer threads; calls `os._exit(1)` if any thread crashes |

### Request Flow — REST Sync

```
Client
  │
  ▼
API Gateway (HTTP)
  │  routes to ALB via VPC Link
  ▼
ALB → ECSIOHandler container
        │
        ├── Thread 1 — ECSQueueRequestHandler (FastAPI/uvicorn)
        │     PUT message on Input Queue
        │     poll DynamoDB Response Store
        │     return response on same connection
        │
        └── Thread 2 — ECSOutputConsumer.run()
              poll Output Queue → write to DynamoDB Response Store
  │
  ▼
Input SQS FIFO Queue
  │
  ▼
ECSAgentRunner container (separate ECS service, auto-scales)
  │  polls Input Queue, runs agent, puts result on Output Queue
  ▼
Output SQS FIFO Queue
  │
  ▼
ECSOutputConsumer (Thread 2)  →  DynamoDB Response Store
```

### Request Flow — REST Async

Identical infrastructure to REST Sync. The difference is purely in `ECSQueueRequestHandler`:

- `POST /api/v1/chat` returns **202 Accepted** with a `request_id` immediately after
  enqueuing (Thread 1 does not wait on DynamoDB).
- `GET /api/v1/chat/{sessionId}?request_id=...` reads from DynamoDB Response Store
  and returns the result when ready (or 404 while still processing).

### Entrypoint Code

**IO container — `app_rest_service.py`** (no agent definitions):

```python
from agentkernel.aws import ECSIOHandler

runner = ECSIOHandler.run

if __name__ == "__main__":
    runner()
```

**Agent Runner container — `app_agent_runner.py`**:

```python
from agentkernel.aws import ECSAgentRunner
from agentkernel.openai import OpenAIModule

OpenAIModule([...])  # agent definitions here only

handler = ECSAgentRunner.run

if __name__ == "__main__":
    handler()
```

### Required AWS Resources

- `aws_sqs_queue` — Input Queue (FIFO)
- `aws_sqs_queue` — Output Queue (FIFO)
- `aws_dynamodb_table` — Response Store (keyed by `request_id`, with TTL)
- IAM for IO container task role: `sqs:SendMessage` on Input Queue; `sqs:ReceiveMessage / DeleteMessage / ChangeMessageVisibility` on Output Queue; `dynamodb:PutItem / GetItem / Query / DeleteItem` on Response Store
- IAM for Agent Runner task role: `sqs:ReceiveMessage / DeleteMessage / ChangeMessageVisibility` on Input Queue; `sqs:SendMessage` on Output Queue

All of these are provisioned automatically by the `yaalalabs/ak-containerized/aws` Terraform module when `enable_queue_mode = true`.

### Required Environment Variables

IO container:

```
AK_EXECUTION__QUEUES__INPUT__URL                   = <input-queue-url>
AK_EXECUTION__QUEUES__OUTPUT__URL                  = <output-queue-url>
AK_EXECUTION__RESPONSE_STORE__DYNAMODB__TABLE_NAME = <response-store-table-name>
```

Agent Runner container:

```
AK_EXECUTION__QUEUES__INPUT__URL               = <input-queue-url>
AK_EXECUTION__QUEUES__OUTPUT__URL              = <output-queue-url>
AK_EXECUTION__QUEUES__INPUT__MAX_RECEIVE_COUNT = <max_receive_count>
```

### Scaling the Agent Runner ECS Service

Unlike Lambda (which auto-scales 1:1 with queue batches), ECS needs an explicit scaling
policy. The recommended approach is **backlog-per-task target tracking**:

1. A Lambda function (EventBridge rule, 1-minute schedule) reads
   `ApproximateNumberOfMessages` from the Input Queue and the current running task count.
2. It computes `BacklogPerTask = queueDepth / max(runningTasks, 1)` and publishes
   this as a custom CloudWatch metric (`Custom/ECS/BacklogPerTask`).
3. An ECS Target Tracking policy scales the Agent Runner service to keep
   `BacklogPerTask` at or below `backlog_target`.

The `scaling_config` block in the `yaalalabs/ak-containerized/aws` module provisions
this automatically. See the [AWS Containerized deployment docs](/docs/deployment/aws-containerized#auto-scaling-for-resilience) for details.

### Key Differences vs Lambda

| Aspect | Lambda | ECS |
|--------|--------|-----|
| Input Queue trigger | Event Source Mapping (push) | `ECSAgentRunner` polls (`ECSSQSConsumer.run`) |
| Partial failure | `batchItemFailures` return value | Failed messages not deleted — visibility timeout retries |
| Scaling | Automatic, 1 Lambda per batch | `backlog-per-task` target tracking policy |
| Response Handler | Separate Lambda triggered by Output Queue ESM | `ECSOutputConsumer` (Thread 2 in IO container) |
| Crash recovery | Lambda restarts automatically | `ThreadRunner` calls `os._exit(1)` → ECS restarts the task |

---

## Summary — Implementation Status

| Component | Lambda | ECS |
|-----------|--------|-----|
| Input/Output SQS Queues | ✅ `modules/queues/` | ✅ `modules/queues/` (same TF module) |
| Agent Runner | ✅ `modules/agent-runner/` | ✅ `ECSAgentRunner` (`akagentrunner.py`) |
| IO Handler / REST Service | ✅ `modules/request-handler/` | ✅ `ECSIOHandler` (`ecs_io_handler.py`) |
| Output Queue Consumer | ✅ `modules/response-handler/` (separate Lambda) | ✅ `ECSOutputConsumer` (Thread 2 in IO container) |
| DynamoDB Response Store | ✅ serverless stack | ✅ containerized stack |
| Thread management | N/A | ✅ `ThreadRunner` (`core/thread_runner.py`) |
| WebSocket Mode | ✅ `modules/websocket-api-gateway/` + `modules/ws-connection-handler/` | ⚠️ `ECSOutputConsumer` supports WebSocket broadcast; API Gateway WebSocket wiring not yet in TF module |
