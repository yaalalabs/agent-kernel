# Current Queue-Mode Implementation: Evidence Pass

Status: verified against `develop` (2026-08-07). Every claim below was read from the code, not
recalled. This note captures the seams the on-prem Kubernetes variant must plug into, the queue
semantics any new backend must reproduce, and the AWS coupling points that must be broken.

## The abstraction seams that already exist

The queue architecture is already half-abstracted; the ABCs live in `deployment/common/` and are
cloud-neutral:

| Seam | Path | What it declares |
|---|---|---|
| Send side | `ak-py/src/agentkernel/deployment/common/queue_handler.py:7` (`QueueHandler`) | `send_message_to_input_queue` (:38), `send_message_to_output_queue` (:63); nested `SendMessageAttributes` (`message_group_id`, `message_deduplication_id`, extra=forbid) and `QueueMessageBody` (`prompt`, `agent`, `session_id`, extra=allow) |
| Receive side | `ak-py/src/agentkernel/deployment/common/queue_consumer.py:5` (`QueueConsumer`) | `poll` (:19), `process_message` (:29), `on_permanent_failure` (:39), `delete_message` (:49); `max_receive_count = 3` class attr (:15) |
| Response store | `ak-py/src/agentkernel/deployment/common/response_store.py:9` (`ResponseStore`) | `add_message`, `get_message(request_id, get_and_delete)`, `delete_message` abstract; `get_message_with_retry` (:37) concrete sync/async poll loop reading `execution.response_store.{retry_count,delay}` |
| REST enqueue/poll | `ak-py/src/agentkernel/deployment/common/rest_handler.py:16` (`RestHandler`) | abstract `get_response_store` (:29) / `get_queue_handler` (:34); `enqueue_and_wait` (:42), `poll_response` (:98); queue mode detected by `execution.queues.input.url is not None` (:40) |
| WS contract | `ak-py/src/agentkernel/deployment/common/websocket_service.py:7` (`WebSocketConnectionStoreABC`), :65 (`WebSocketHandlerABC`) | connection add/get/delete by `user_id`/`connection_id`; abstract `get_client`, `construct_endpoint_url`, `send`; concrete `broadcast` (:201) with `MessageType` envelope (`CHAT_RESPONSE`, `CHAT_QUEUED`, `SYSTEM_RESPONSE`, `STREAM_CHUNK`) |
| Thread orchestration | `ak-py/src/agentkernel/deployment/common/thread_runner.py` (`ThreadRunner`) | N peer threads, `shutdown_event` singleton, graceful drain |

The only concrete implementations of the queue seams are SQS-bound:

- `SQSHandler` (`deployment/aws/core/sqs_handler.py:14`): `import boto3` at :7; FIFO
  `MessageGroupId`/`MessageDeduplicationId`; custom message attributes carry `request_id`,
  `user_id`, `endpoint_url` (:290-292); `message_group_id` defaults to the body's `session_id`
  (:346, :388).
- `ECSSQSConsumer` (`deployment/aws/containerized/core/sqs_consumer.py:14`): `import boto3` at :8;
  long-poll `receive_message` with `MaxNumberOfMessages = execution.queues.batch_size` (:66-71);
  retry via visibility timeout (unacked messages return automatically); receive count read from the
  SQS `ApproximateReceiveCount` attribute (:110); permanent failure when
  `receive_count > max_receive_count` → `on_permanent_failure` then delete (:113-117); the
  `_consumer_loop`/`run` machinery (:133-175) is backend-agnostic apart from those primitives
  (thread names are `sqs-consumer-{i}`).

## Business logic that is queue-agnostic but SQS-hosted today

- `ECSAgentRunner` (`deployment/aws/containerized/akagentrunner.py:13`): parse `BaseRunRequest`
  from the message body, extract routing attributes (`request_id` required, `user_id`,
  `endpoint_url`, group/dedup IDs: :48-74), run `ChatService.process_chat_request`, forward the
  reply to the output queue via `SQSHandler.send_message_to_output_queue` (:77-94). STREAM
  sibling `ECSStreamAgentRunner` (:141) fans out one output message per chunk with a per-chunk
  dedup suffix `{receive_count}-{chunk_count}` (:213-220).
- `ECSOutputConsumer` (`deployment/aws/containerized/akoutputconsumer.py:15`): REST modes → write
  `{session_id, request_id, body}` to the response store (:77-83); ASYNC/STREAM → broadcast via
  `AWSWebSocketHandler` to `endpoint_url` + `user_id` from message attributes (:169-196).
- `ECSIOHandler` (`deployment/aws/containerized/ecs_io_handler.py:10`): two `ThreadRunner` tasks:
  `rest-api` (uvicorn, `awaited_on_shutdown=False`) + `output-queue-consumer`.

None of this logic is SQS-specific except: (a) inheritance from `ECSSQSConsumer`, (b) direct
`SQSHandler` classmethod calls, (c) reading attributes through `SQSHandler.get_message_*`
helpers with SQS record shapes (PascalCase/camelCase keys).

## The queue-semantics contract a new backend must reproduce

From the SQS FIFO usage above:

1. **Per-session ordering**: `message_group_id = session_id`; one session's messages processed in
   order, different sessions in parallel (SQS FIFO `deduplication_scope = messageGroup`,
   `fifo_throughput_limit = perMessageGroupId`: `ak-deployment/ak-aws/containerized/modules/queues/main.tf:5,41`).
2. **Deduplication**: explicit `message_deduplication_id` = `request_id` on input (:59 of
   `rest_handler.py`), `{dedup}-{receive_count}-{chunk}` per stream chunk.
3. **At-least-once + bounded retry**: unacked messages redelivered (visibility timeout); per-message
   delivery count surfaced to the consumer; after `max_receive_count` deliveries →
   `on_permanent_failure` hook, then acknowledge/remove.
4. **Routing metadata as message attributes** (not body fields): `request_id` (required), `user_id`,
   `endpoint_url` (WS push target, ASYNC/STREAM only).
5. **Batch fetch** with `execution.queues.batch_size`; N consumer threads per replica
   (`no_of_consumers`: input default 5, output default 2).
6. **Failure surfacing**: permanent failure on the input queue produces an error message on the
   output queue; permanent failure on the output queue produces an error entry in the response
   store or an error WS frame: so the waiting client never hangs silently.

## Config: current shape and the gap

`ak-py/src/agentkernel/core/config.py` (line numbers re-verified 2026-08-11 after PR #613):

- `_ExecutionConfig` (:384): `mode` (`rest_sync | rest_async | stream | async`,
  `model.py:162-170`), `queues`, `response_store`.
- `_QueuesConfig` (:356): `input`/`output`/`batch_size`. `_InputQueueConfig` (:322):
  `url` (described as SQS queue URL), `max_receive_count=3`, `no_of_consumers=5`;
  `_OutputQueueConfig` (:339): same with `no_of_consumers=2`.
- **Gap**: unlike `session`, `thread`, `multimodal`, `execution.response_store`, the queues block
  has **no `type` discriminator and no per-backend sub-models**. Selecting kafka/nats requires
  adding that, following the house factory pattern (`core/util/factory.py`: if/elif built-ins +
  dotted-path BYO: see spec 541).
- `_ResponseStoreConfig` (:313): `type` pattern `^(redis|valkey|dynamodb)$`; Redis and Valkey
  backends already exist and are on-prem-ready, but the factory (`ResponseDBHandler`) and all three
  store classes live under `deployment/aws/core/response_store/`: a packaging wrinkle: the
  cloud-portable Redis/Valkey stores are namespaced (and exported) under `aws`.
- `_WebSocketAPIConfig` (:104-107): `endpoint_url`, `chat_route`, `connection_table`
  (DynamoDB-only connection store).

## Terraform → app config bridge (contract to replicate in Helm)

The ECS modules inject config exclusively via `AK_` env vars
(`ak-deployment/ak-aws/containerized/modules/agent-runner/main.tf:7-22`,
`modules/rest-service/main.tf:18-28`):
`AK_EXECUTION__QUEUES__INPUT__URL`, `AK_EXECUTION__QUEUES__OUTPUT__URL`,
`AK_EXECUTION__QUEUES__INPUT__MAX_RECEIVE_COUNT`, `AK_EXECUTION__QUEUES__BATCH_SIZE`,
`AK_EXECUTION__MODE`, `AK_EXECUTION__RESPONSE_STORE__DYNAMODB__TABLE_NAME`. The application's
committed `config.yaml` declares the mode/types; infrastructure injects only connection details.
A Helm chart should preserve exactly this split (values → env vars, never a mounted config.yaml
that overwrites the app's).

## AWS coupling points the on-prem variant must break

1. **Queue transport**: `boto3` SQS client in `SQSHandler` + `ECSSQSConsumer`.
2. **Record shape**: `SQSHandler.get_message_system_attributes` / `get_message_custom_attributes`
   normalize boto3/Lambda record dicts; consumers index `record["Body"]`, `record["MessageId"]`,
   `record["Attributes"]["ApproximateReceiveCount"]`, `record["ReceiptHandle"]`.
3. **WS push transport**: `AWSWebSocketHandler` (`deployment/aws/core/websocket_service.py:118`)
   pushes via API Gateway Management API `post_to_connection`; connections stored in DynamoDB
   (`WebSocketConnectionStore`, :13). On ECS, the WS connection itself terminates on API Gateway,
   so any pod can push to any connection through the management endpoint. **On Kubernetes there is
   no such indirection**: the WebSocket terminates on a specific uvicorn pod, so output delivery
   must reach that specific pod (see `kubernetes-deployment.md` for options).
4. **Response store DynamoDB backend** (Redis/Valkey already portable).
5. **Docker images**: queue-mode examples use two thin images
   (`examples/aws-containerized/openai-stream-queue-mode/deploy/Dockerfile.{rest-service,agent-runner}`)
   with entrypoints `ECSIOHandler.run(...)` / `ECSAgentRunner.run()`: the same two-process shape
   maps directly to two k8s Deployments.

## Prior art and deferred items relevant to #495

- Spec 494 (sandbox) defers a `kubernetes` sandbox provider
  (`docs/specs/494-sandbox-capability/plan.md:211-223`) and names a "`k8s_pod` broker flavor
  (future, tied to full on-premise support)" (`design.md:389`, `plan.md:260-261`).
- `ak-deployment/ak-aws/containerized/variables.tf:156-161` declares `container_type` validated
  against `["ecs", "eks"]` but no resource references it: an unused EKS hook.
- Neither Azure nor GCP containerized deployments have a queue mode; ECS is the only containerized
  queue-mode target today.
- `.github/workflows/sync-terraform.yaml:17-52` publishes each `ak-deployment/*` module to its own
  repo/registry; a new on-prem deliverable must join this (or an equivalent chart-publishing) flow.
- Docs surfaces an on-prem section would extend: `docs/sidebars.js:61-90` (Deployment category),
  `docs/docs/deployment/overview.md`, `docs/docs/advanced/queue-mode-guide.md:353`
  (implementation-status matrix).
