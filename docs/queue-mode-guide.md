# Queue Mode — How It Works and How to Add It to ECS

This document explains what's already built for the Lambda (serverless) queue modes and
how to replicate the same pattern in the ECS (containerized) deployment.

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

## How to Add Queue Mode to ECS (Containerized)

The ECS deployment is fundamentally the same pipeline, **except Lambda functions are
replaced by a long-running ECS service** that runs two threads:

| Thread | Responsibility |
|--------|---------------|
| Thread 1 | Runs the FastAPI/REST service (receives requests, returns responses) |
| Thread 2 | Polls the Output Queue and writes to DynamoDB (REST modes) or sends via WebSocket |

The **Agent Runner** is already a separate ECS service that polls the Input Queue.

### REST Sync — ECS Queue Mode

```
Client
  │
  ▼
API Gateway (HTTP) — existing aws_apigatewayv2_api.http_api
  │  routes to ALB via VPC Link — existing aws_apigatewayv2_integration.alb_proxy
  ▼
ALB → ECS REST Service (Thread 1)
  │  PUT message on Input Queue
  │  wait / poll DynamoDB Response Store
  │  return response on same connection
  │
  │  (Thread 2 running in same container)
  │  poll Output Queue → write to DynamoDB Response Store
  ▼
Input SQS FIFO Queue
  ▼
Agent Runner ECS Service (separate ECS task/service)
  │  polls queue, processes, puts result on Output Queue
  ▼
Output SQS FIFO Queue
  ▼
ECS REST Service Thread 2  →  DynamoDB Response Store
```

New AWS resources needed:
- `aws_sqs_queue` — Input Queue (FIFO)
- `aws_sqs_queue` — Output Queue (FIFO)
- `aws_dynamodb_table` — Response Store (keyed by `session_id`, with TTL)
- IAM policies giving the REST Service ECS Task Role:
  - `sqs:SendMessage` on Input Queue
  - `sqs:ReceiveMessage / DeleteMessage / ChangeMessageVisibility` on Output Queue
  - `dynamodb:PutItem / GetItem / Query / DeleteItem` on Response Store
- IAM policies giving the Agent Runner ECS Task Role:
  - `sqs:ReceiveMessage / DeleteMessage / ChangeMessageVisibility` on Input Queue
  - `sqs:SendMessage` on Output Queue
- Existing API Gateway + ALB routes are reused as-is; only the application code changes
  (Thread 2 is added to the REST Service container).

Environment variables to inject into the REST Service container:

```
AK_EXECUTION__QUEUES__INPUT__URL        = <input-queue-url>
AK_EXECUTION__QUEUES__OUTPUT__URL       = <output-queue-url>
AK_EXECUTION__RESPONSE_STORE__DYNAMODB__TABLE_NAME = <response-store-table-name>
```

Environment variables for the Agent Runner container:

```
AK_EXECUTION__QUEUES__INPUT__URL        = <input-queue-url>
AK_EXECUTION__QUEUES__OUTPUT__URL       = <output-queue-url>
AK_EXECUTION__QUEUES__INPUT__MAX_RECEIVE_COUNT = <max_receive_count - 1>
```

### REST Async — ECS Queue Mode

Identical infrastructure to REST Sync. The difference is purely in the application:

- `POST /api/v1/chat` returns **202 Accepted** with a `session_id` immediately after
  enqueuing (Thread 1 does not wait).
- `GET /api/v1/chat/{sessionId}` reads from DynamoDB Response Store and returns the
  result when ready (or 202 if still processing).

No additional AWS resources are needed beyond the REST Sync setup. The API Gateway already
supports both `POST` and `GET` routes to the ALB.

### Scaling the Agent Runner ECS Service

Unlike Lambda (which auto-scales 1:1 with queue batches), ECS needs an explicit scaling
policy. The recommended approach is **backlog-per-task target tracking**:

1. A Lambda function (or EventBridge scheduled rule) periodically reads
   `ApproximateNumberOfMessages` from SQS and the current running task count.
2. It computes `BacklogPerTask = queueDepth / runningTasks` and publishes this as a
   custom CloudWatch metric.
3. An ECS Target Tracking scaling policy scales the Agent Runner service to keep
   `BacklogPerTask` at or below the configured target.

This is covered in detail in `scalability.md` under the **SQS + ECS → Scaling** section.

### Key Differences vs Lambda

| Aspect | Lambda | ECS |
|--------|--------|-----|
| Input Queue trigger | Event Source Mapping (push) | Agent Runner polls the queue |
| Partial failure reporting | `batchItemFailures` return value | Failed messages not deleted (visibility timeout) |
| Scaling | Automatic, 1 Lambda per batch | Manual target tracking policy |
| Response Handler | Separate Lambda triggered by Output Queue ESM | Thread 2 inside the REST Service container |
| Session DB writes | Response Handler Lambda | REST Service Thread 2 |

---

## Summary of What's Already Built

| Component | Lambda (done) | ECS (todo) |
|-----------|--------------|------------|
| Input/Output SQS Queues | ✅ `modules/queues/` | ❌ needs new TF resources |
| Agent Runner | ✅ `modules/agent-runner/` | ❌ separate ECS service |
| Request Handler / REST Service | ✅ `modules/request-handler/` | ❌ add queue env vars + thread 2 |
| Response Handler | ✅ `modules/response-handler/` | ❌ merged into REST Service Thread 2 |
| DynamoDB Response Store | ✅ provisioned inside serverless stack | ❌ needs new TF resource |
| WebSocket Mode | ✅ `modules/websocket-api-gateway/` + `modules/ws-connection-handler/` | ❌ not yet |
