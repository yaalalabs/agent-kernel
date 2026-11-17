# #870: Move ECS onto the shared queue pipeline — Implementation Spec

ECS queue mode stops running its own runner, output consumer and IO entry point, and runs the shared pipeline
classes instead. The requirements come from [design.md](design.md). This spec covers how to build it: one
receive-side fix in the SQS transport, one new `IOHandler.run` parameter, one `endpoint_url` guard on the AWS push
handler, a queue hand-off in `AWSWebsocketAPI.run`, one Terraform validation, and the deletion of four modules.

_Evidence at `develop` @ `b982c7b8`. None of the files cited here changed between `e85bbcb6` (the design's
snapshot) and `b982c7b8`, so the design's line numbers still hold. Paths are relative to `ak-py/src/agentkernel/`
unless they start with a top-level folder._

## Design

### 1. SQS reader keeps the dedup ID

`SQSTransportConsumer._to_envelope` (`pipeline/transport/sqs.py:222-232`) gains one field:

```python
return QueueMessage(
    ...,
    dedup_id=system_attributes.get("MessageDeduplicationId"),  # FIFO only; None on standard queues
    ...
)
```

- `fetch` already requests `AttributeNames=["All"]` (`sqs.py:212`), so SQS returns the attribute on FIFO queues.
- `AgentRunner._send_to_output` already derives the reply ID from it (`pipeline/agent_runner.py:332-334`): `<id>`
  for a whole reply or a permanent-failure 500, and `<id>-<receive_count>-<n>` or `<id>-<receive_count>-error` for
  chunks. These match what `ECSAgentRunner` sends (`deployment/aws/containerized/akagentrunner.py:123-124`,
  `:257`, `:282`).
- The Service Bus transport already does the same on receive (`pipeline/transport/servicebus.py:192`).

`build_send_message_kwargs` (`sqs.py:125-151`) makes sure every dedup ID it sends is one SQS accepts:

```python
_SQS_DEDUP_ID = re.compile(r"[!-~]{1,128}")  # SQS: 1-128 printable ASCII characters, no spaces

def _sqs_dedup_id(dedup_id: str | None) -> str | None:
    """A dedup ID SQS accepts: the ID itself, or its SHA-256 hex digest when SQS would reject it."""
    if dedup_id is None or _SQS_DEDUP_ID.fullmatch(dedup_id):
        return dedup_id
    return hashlib.sha256(dedup_id.encode()).hexdigest()
```

- It is called on `message_deduplication_id` inside `build_send_message_kwargs`.
- It is a module-level function because it is small and stateless, and the SQS wire helpers next to it are
  functions too (`sqs.py:100-191`).
- One place covers every SQS sender. `SQSTransport.send` (`sqs.py:255-262`) and `SQSHandler` both build their
  kwargs here (`sqs.py:1-7`, `tests/test_pipeline_sqs_transport.py:85-91`). That covers the ECS WebSocket
  enqueue, the Lambda runner and the pipeline runners.
- Why it is needed: on ECS WebSocket frames, `request_id` is set by the client and has no length limit
  (`core/model.py:764`). It becomes the input's dedup ID (`websocket_api.py:356`). A 125-character ID is accepted
  at enqueue, but its chunk IDs (`<id>-1-0`) are over 128 characters. SQS would then reject every chunk and the
  error chunk, and the client would hang. `ECSStreamAgentRunner` has the same bug today.
- The digest is deterministic, so a resent whole reply (`<id>`) still deduplicates against its first send.
  Streamed chunk IDs (`<id>-<receive_count>-<n>`) change on redelivery, so a redelivered input's chunks are
  not deduplicated against the first attempt's, as before this change. Different chunk suffixes give
  different digests.
- Known limit: a valid ID equal to another ID's digest maps to the same value. That takes a client sending the
  digest of its own other ID in the same session within SQS's 5-minute window, and only drops its own message.

### 2. `IOHandler.run(ws_handler=)`

`pipeline/io_handler.py`:

```python
@classmethod
def run(
    cls,
    handlers: list[RESTRequestHandler] | None = None,
    pollers: list["PollerRunner"] | None = None,
    gateways: list["GatewayRunner"] | None = None,
    request_handler: RequestHandler | None = None,
    ws_handler: WebSocketHandlerABC | None = None,  # new: replaces pod push for WebSocket delivery
) -> None: ...

@classmethod
def _validate_topology(cls, transport_type: str, config, pod_push: bool = True) -> None: ...
```

Rules:

1. `ws_handler` goes to the response handler thread only: `ResponseHandler(ws_handler=ws_handler)` in place of
   `ResponseHandler()` (`io_handler.py:131`). `None` keeps today's lazy `PodPushWebSocketHandler`
   (`pipeline/response_handler.py:55-60`).
2. When `ws_handler` is set, both pod-push checks are skipped. They only protect the pod-push path:
   - the shared session connection store check (`io_handler.py:86-94`): the `if` gains `and ws_handler is None`.
   - the `push_auth_token` check (`io_handler.py:222-231`): `run` passes `pod_push=ws_handler is None`, and the
     check runs only when `pod_push` is true. The default `True` keeps existing direct callers of
     `_validate_topology` working (`tests/test_pipeline_io_handler.py:82-136`).
3. All other topology checks still run: REST response store, SSE chunk store, A2A/MCP shared store
   (`io_handler.py:232-261`).
4. `WebSocketHandlerABC` is a plain import from `pipeline/ws/base.py`, which is inside `pipeline`, so there is no
   cycle to break. `pipeline` still imports nothing from `deployment/`.
5. Not validated: `ws_handler` on the `in_memory` transport. Its only caller (§4) never passes it there. A BYO
   caller who does gets both the co-hosted pod handlers and their own push handler, which is their choice.

### 3. `ResponseHandler` passes `endpoint_url` on

`pipeline/response_handler.py`:

- `_broadcast` (`:286`) and `_broadcast_error` (`:297`) both call
  `broadcast(endpoint_url=message.attributes.get(ATTR_ENDPOINT_URL), message=..., user_id=..., message_type=...)`.
- `ATTR_ENDPOINT_URL` already exists (`pipeline/envelope.py:13`) and the runner already forwards it
  (`agent_runner.py:34`).
- `PodPushWebSocketHandler.broadcast` ignores it (`pipeline/ws/push.py:141-142`), so pod-push delivery does not
  change.

### 4. `AWSWebSocketHandler` refuses to push without an endpoint

`deployment/aws/core/websocket_service.py`, `AWSWebSocketHandler` (`:141`) overrides `broadcast`:

```python
def broadcast(self, endpoint_url=None, message=None, user_id=None, connection_ids=None, message_type=None) -> None:
    if not endpoint_url:
        raise ValueError("endpoint_url is required for API Gateway WebSocket delivery")
    super().broadcast(endpoint_url, message, user_id, connection_ids, message_type)
```

- This is what keeps "missing `endpoint_url` fails the delivery" (design, Response delivery) without
  `ResponseHandler` knowing about AWS. Today `ECSOutputConsumer` checks it itself
  (`deployment/aws/containerized/akoutputconsumer.py:175-176`).
- Without the guard, `get_client(None)` (`websocket_service.py:148-160`) would build a Management API client
  for the default regional endpoint, and `post_to_connection` would fail in a confusing way.
- The other callers always pass an endpoint, so they see no change. Lambda checks it first
  (`deployment/aws/serverless/akresponsehandler.py:111-112`, `:200`, `:217`). The Lambda router and the ECS
  WebSocket routes build it from the event or headers (`deployment/aws/serverless/core/router/ws_lambda.py:123`,
  `deployment/aws/containerized/core/api/websocket_api.py:76-83`).

### 5. `AWSWebsocketAPI.run` hands off to `IOHandler`

`deployment/aws/containerized/core/api/websocket_api.py:519-525`:

```python
@classmethod
def run(cls, handlers: list[RESTRequestHandler] | None = None) -> None:
    system_handler, app_handler = cls.get_default_handlers()
    all_handlers = [system_handler, app_handler, *(handlers or [])]
    if QueueTransportFactory.resolve_type() == "in_memory":
        return super().run(handlers=all_handlers)  # direct mode: unchanged
    from ......pipeline.io_handler import IOHandler

    # Replies are pushed through API Gateway to each message's endpoint_url, not to gateway pods.
    IOHandler.run(handlers=all_handlers, ws_handler=system_handler.get_websocket_handler())
```

- The push handler is the system handler's own lazily built `AWSWebSocketHandler`
  (`websocket_api.py:61-65`). It is built over `websocket_api.connection_table`, which the base constructor
  already validates (`websocket_api.py:45-46`). That is the same build `ECSOutputConsumer._get_websocket_handler`
  does (`akoutputconsumer.py:43-53`), so no builder code moves or is copied.
- `get_default_handlers` builds the system handler, which raises `AKConfigError` when there is no `identity`
  block (`websocket_api.py:126-127`). This happens before any thread starts, so it replaces the identity check in
  `ECSIOHandler` (`ecs_io_handler.py:62-65`).
- `IOHandler.run` also mounts the pipeline `RequestHandler` on `/api/v1/chat`. In WebSocket mode it answers 400
  (`pipeline/request_handler.py:439-442`), and API Gateway WebSocket never routes to it (`api_gateway.tf:44`
  creates no HTTP routes). Its paths do not overlap the `/ws/*` routes.
- The `in_memory` test matches `RESTAPI.run`'s own hand-off (`api/http.py:103-110`). A config with no `queues`
  block resolves to `in_memory` (`pipeline/transport/base.py:117-119`), so direct-mode ECS
  (`examples/aws-containerized/openai-stream/app.py:50`) keeps calling `RESTAPI.run` and is unaffected.
- No `request_handler` parameter (design Non-goals: no HTTP routes in WebSocket mode).

### 6. Deleted modules and exports

| Deleted | Replaced by |
|---|---|
| `deployment/aws/containerized/akagentrunner.py` (`ECSAgentRunner`, `ECSStreamAgentRunner`, `ECSRealtimeAgentRunner`) | `AgentRunner.run` (`pipeline/agent_runner.py:193-209`) |
| `deployment/aws/containerized/akoutputconsumer.py` (`ECSOutputConsumer`) | `ResponseHandler`, started by `IOHandler.run` |
| `deployment/aws/containerized/ecs_io_handler.py` (`ECSIOHandler`) | `IOHandler.run` (REST modes), `AWSWebsocketAPI.run` (WebSocket mode) |
| `deployment/aws/containerized/core/api/rest_api.py` (`AWSRestAPI`, `ECSQueueRequestHandler`) | `RequestHandler`, mounted by `IOHandler.run` |

Export edits:

- `deployment/aws/containerized/__init__.py`: keeps only
  `from .core.api import AWSWebsocketAPI, ECSWebSocketSystemRequestHandler`.
- `deployment/aws/containerized/core/api/__init__.py`: drops the `rest_api` import line.
- `deployment/aws/__init__.py`: drops `AWSRestAPI`, `ECSAgentRunner`, `ECSIOHandler` and `ECSOutputConsumer` from
  `_LAZY_EXPORTS` (`:15-19`) and from the `TYPE_CHECKING` import (`:38-45`).
- No aliases or shims. This is a `feat!:` change (design, Breaking change).

Comment-only references to the deleted names get reworded so nothing points at a class that no longer exists:

- `api/http.py:98`, `:161`
- `pipeline/agent_runner.py:46`
- `pipeline/io_handler.py:125`
- `pipeline/response_handler.py:26`
- `pipeline/transport/sqs.py:66`
- `sandbox/broker/queue_worker.py:315`
- `deployment/aws/containerized/core/api/websocket_api.py:350`

Kept: `ECSSQSConsumer`, `RawQueueConsumer` and `SQSHandler` (design Non-goals). After this change
`ECSSQSConsumer` has no subclass in the tree, but it is still exported as a public base (`aws/__init__.py:21`).

### 7. Terraform: refuse SSE on ECS queue mode

Add a second `validation` to `variable "message_type"` in `ak-deployment/ak-aws/containerized/variables.tf`
(`:276-284`):

```hcl
validation {
  condition     = !(var.queue_mode && var.execution_mode == "rest_sync" && var.message_type == "delta")
  error_message = "rest_sync with message_type = \"delta\" (SSE) is not supported with queue_mode = true: the HTTP API buffers streamed responses. Use execution_mode = \"async\" with message_type = \"delta\" (WebSocket)."
}
```

- This uses the same cross-variable style as the existing check on `execution_mode` (`variables.tf:270-273`).
- A `null` `message_type` passes, because `null == "delta"` is false.

### Consumer changes

- **ECS runner scripts:** `ECSAgentRunner.run` becomes `AgentRunner.run`, imported with
  `from agentkernel.pipeline import AgentRunner`. Mode dispatch, including realtime, now happens inside
  `AgentRunner.run`.
- **ECS REST IO scripts (`rest_sync`, `rest_async`):** `ECSIOHandler.run(handlers=...)` becomes
  `IOHandler.run(handlers=...)`. The chat route is the pipeline `RequestHandler`, so the routes stay the same:
  `/agents`, `/chat`, `/chat/poll` (`request_handler.py:373-377` vs the deleted `rest_api.py` through
  `RestHandler.get_router`, `request_handler.py:336-344`).
- **ECS WebSocket IO scripts (`async`):** `ECSIOHandler.run()` becomes `AWSWebsocketAPI.run()`.
  `@AWSWebsocketAPI.register` routes do not change.
- **`ECSWebSocketRequestHandler`:** no change. It still enqueues through `SQSHandler` with the `endpoint_url`
  attribute and `request_id` as the dedup ID (`websocket_api.py:349-366`).
- **Verified unchanged:**
  - Lambda: `ServerlessAgentRunner`, the serverless `ResponseHandler`, and `LambdaWSHandler`. Their only touch
    point is the §4 guard, and they already pass an endpoint.
  - Helm/Azure/GCP: they call `IOHandler.run` without `ws_handler`.

### Config changes

- No config changes. No new `AKConfig` fields. The ECS IO process is selected by the existing
  `execution.queues.type` (`core/config.py:827`) and the existing `websocket_api.connection_table`
  (`core/config.py:126`).
- One Terraform validation (§7). No new variables, container commands or env vars.

### Behavioural changes

All intentional.

1. **Pipeline SQS replies carry `MessageDeduplicationId`.** This applies to every user of the SQS transport, not
   only ECS. On a FIFO output queue with content-based dedup, the explicit ID now wins over the content hash. That
   is harmless: the reply IDs are unique per request and chunk. Without it, ECS's FIFO output queue
   (`content_based_deduplication = false`, `modules/queues/main.tf:46`) would reject every reply.
   A dedup ID SQS would reject (over 128 characters, or outside printable ASCII) is now sent as its SHA-256
   digest instead of failing. This applies to every SQS sender, Lambda included (§1). IDs SQS already accepted
   are sent unchanged.
2. **ECS gains** `integration` / `reply_*` delivery, thread reply recording, AG-UI and A2A/MCP routing, the
   handlers marked `requires_pipeline` (webhook host, AG-UI, thread request handler), `requests=` on
   `ChatService`, and SIGTERM drain on the runner and IO containers (design, Agent runner and IO entry point).
3. **Runner polling** uses `SQSTransportConsumer`'s 20 s long poll (`sqs.py:197-214`). Before, it was
   `ECSSQSConsumer.poll` with no `WaitTimeSeconds` (`core/sqs_consumer.py:96-101`). This means fewer empty
   receives, and a graceful drain can wait up to 20 s.
4. **Async + delta needs `user_id`** where it used to need `endpoint_url` (`agent_runner.py:367-368` vs
   `akagentrunner.py:208-211`). ECS frames carry both (`websocket_api.py:353-361`). The missing `endpoint_url`
   now fails at delivery instead, through §4.
5. **Edge validation on the REST chat route.** `RequestHandler.run_chat` (`request_handler.py:384-399`) returns
   400 for a missing `session_id` or prompt, or a request `ChatService` would refuse, before anything is
   enqueued. Before, these were enqueued and the runner's reply carried the error.
6. **Stored `session_id` falls back to the message group.** `_store_response` uses `body.session_id or group_id`
   (`response_handler.py:238`), where ECS stored `body.get("session_id")`, which could be `None`
   (`akoutputconsumer.py:156`).
7. **WebSocket permanent failure with no `endpoint_url`.** ECS logged a warning
   (`akoutputconsumer.py:123-124`). Now the §4 guard raises inside `on_permanent_failure`, and its catch-all logs
   it with `log.exception` (`response_handler.py:146-147`). The client still gets nothing, as before.
8. **A2A/MCP** are served on ECS when a shared response store is configured, instead of being refused up front
   (`ecs_io_handler.py:47`).
9. **SSE on ECS queue mode** is refused at `terraform plan` instead of at container start
   (`ecs_io_handler.py:50-55`). This has a known gap: `message_type: delta` set only in `config.yaml` (design,
   SSE refusal).

**Non-changes:**

- SQS wire format: attribute names, group ID and dedup ID values.
- Response store records: `session_id`, `request_id`, `status_code`, `body`.
- The DynamoDB connection table.
- Container commands and env vars.
- `AWSWebsocketAPI.register` and `run(handlers=)` signatures.
- `ECSWebSocketSystemRequestHandler` / `ECSWebSocketRequestHandler` behaviour.
- `IOHandler.run` behaviour when `ws_handler` is `None`.
- Records already in the response store or in flight on the queues are read back the same way after the change,
  so a rolling deploy delivers in both directions (design, Rolling deploy compatibility).

## Error handling

| Failure | Where it surfaces |
|---|---|
| No `identity` block, WebSocket mode | `AKConfigError` from `get_default_handlers()` in `AWSWebsocketAPI.run`, before any thread starts |
| No `websocket_api.connection_table.table_name` | `ValueError` from `ECSWebSocketHandlerBase.__init__` (`websocket_api.py:45-46`), before any thread starts |
| REST queue mode without a shared response store | `AKConfigError` from `IOHandler._validate_topology` (`io_handler.py:236-241`) |
| A2A/MCP without a shared response store | `AKConfigError` (`io_handler.py:250-261`) |
| Output message without `user_id` (WebSocket) | `ValueError` in `_broadcast`. `ConsumerLoop` retries up to `output.max_receive_count`, then `on_permanent_failure` |
| Output message without `endpoint_url` (ECS WebSocket) | `ValueError` from the §4 guard. Same retry path |
| API Gateway `GoneException` | Stale connection deleted, no raise (`websocket_service.py:219-221`), unchanged |
| Other `post_to_connection` `ClientError` | Logged and swallowed (`websocket_service.py:223-224`), unchanged. The message is acked, as today |
| Input message without `request_id` in attributes or body | `ValueError` in `_resolve_request_metadata` (`agent_runner.py:318-319`). Retries, then a 500 reply |
| FIFO reply with no dedup ID (the bug §1 fixes) | Can no longer happen on SQS input that carries a dedup ID. A standard input queue gives `None`, which is valid for a standard output queue |

**Concurrency.** One `AWSWebSocketHandler` is shared by the API thread (the system handler's `$default` reply and
the route offloads) and `output.no_of_consumers` response handler threads. Today it is already shared, by the
`asyncio.to_thread` offloads and by `ECSOutputConsumer`'s consumer threads (a class attribute), so the risk is no
higher. `get_client`'s unlocked cache can at worst build two boto3 clients for one endpoint, and boto3 clients
are thread-safe. The DynamoDB `Table` resource in `WebSocketConnectionStore` is not: boto3 documents
resources as not thread-safe. It is already shared across the API thread's offloads and the output consumer
threads today, so this change does not add the risk, and moving the store to a boto3 client is left to a
follow-up.

**Per-operation cost.** None added. The dedup mapping is one dict read per fetched record. The endpoint guard is
one truthiness check per broadcast.

## Testing

Run: `cd ak-py && uv run pytest tests/ -q`, and before the PR, `make lint-check-all` from the repo root.

### New and changed tests

- **`tests/test_pipeline_sqs_transport.py`** (dedup regression, SQS-only per design)
  - `_record()` gains `"MessageDeduplicationId": "r1"` under `Attributes`.
    `test_fetch_maps_boto3_record_to_envelope` asserts `message.dedup_id == "r1"`.
  - New `test_fetch_without_a_dedup_id_maps_to_none` (standard queue).
  - New `TestDedupIdBounds` on `build_send_message_kwargs`:
    - A 128-character ID is sent unchanged.
    - A 129-character ID, and an ID containing a space, are each sent as a 64-character hex digest. The same
      input always gives the same digest.
    - A 128-character ID with chunk suffixes `-1-0` and `-1-1` gives two different digests.
  - New `test_reply_sent_from_a_fetched_record_carries_its_dedup_id`: fetch a record with a dedup ID, run it
    through `AgentRunner._send_to_output` on an `SQSTransport` over a mocked client, and assert the
    `send_message` kwargs carry `MessageDeduplicationId="r1"`. With a chunk suffix, assert `"r1-2-0"`.
- **`tests/test_pipeline_response_handler.py`**
  - `_FakeWSHandler.broadcast` records `endpoint_url`.
  - New tests: `_broadcast` and `_broadcast_error` pass the message's `endpoint_url` attribute, or `None` when it
    is absent.
- **`tests/test_pipeline_io_handler.py`**
  - New `TestExternalWebSocketHandler`, which stubs `build_app`, `uvicorn.Server`, `_install_signal_handlers` and
    `ThreadRunner.run` like `TestPollerCoHosting` (`:361-364`). Its tests:
    - async on a broker with `ws_handler` and no push token or shared connection store: starts.
    - the `response-handler` task builds `ResponseHandler(ws_handler=<the handler>)`. Patch
      `agentkernel.pipeline.io_handler.ResponseHandler` and call the task's `execution_function`.
    - without `ws_handler`, the existing push-token refusal still fires.
- **`tests/test_websocket_service_broadcast.py`**
  - New tests: `AWSWebSocketHandler.broadcast` raises `ValueError` with no `endpoint_url` and never calls
    `get_client`. With one, it sends to each connection.
- **`tests/test_ecs_websocket_routes.py`**: new `TestQueueHandOff` for the `AWSWebsocketAPI.run` hand-off, kept
  beside the other `AWSWebsocketAPI` tests. `test_ecs_io_handler.py` is deleted with `ECSIOHandler`. Its tests:
  - `sqs` transport: `IOHandler.run` is called with the system and app handlers plus the caller's, and with
    `ws_handler` being the system handler's `AWSWebSocketHandler`. Patch
    `agentkernel.pipeline.io_handler.IOHandler.run`.
  - `in_memory`: `RESTAPI.run` path (`uvicorn.run` patched); `IOHandler.run` is not called.
  - no `identity` block: `AKConfigError` before `IOHandler.run`.
- **New `tests/test_ecs_shared_pipeline.py`**: two tests (design, Acceptance coverage and Rolling deploy
  compatibility). `boto3.client` is a `MagicMock`; there is no fake queue. Per-mode delivery and Slack are already
  covered by the pipeline suites, so they get no ECS copy.
  - **Rolling deploy (WS delta):**
    - Old IO → new runner: build a raw record shaped like `ECSWebSocketRequestHandler._enqueue_chat`'s, with
      `MessageDeduplicationId="r1"`, `MessageGroupId`, and `request_id` / `user_id` / `endpoint_url`
      attributes. Map it with `SQSTransportConsumer._to_envelope` and run it through `StreamAgentRunner` over
      `SQSTransport`, with a stubbed `ChatService` yielding two chunks. Each `send_message` carries
      `endpoint_url` and `MessageDeduplicationId` `r1-1-0`, `r1-1-1`, ….
    - Old runner → new IO: a hand-built output record shaped like the old `ECSAgentRunner._send_to_output_queue`
      (attributes `request_id`, `user_id`, `endpoint_url`, `status_code`) goes through
      `ResponseHandler(ws_handler=AWSWebSocketHandler)`. `post_to_connection` is called on the client built for
      its `endpoint_url`, with `STREAM_CHUNK`. In REST mode the same record is stored with its `status_code`.
  - **Mount:** `IOHandler.run(handlers=[WebhookRESTRequestHandler(...), AGUIPipelineRequestHandler(...)],
    request_handler=ThreadRequestHandler(...))` on an `sqs` config with a Redis response store builds the app
    without error (server and threads stubbed). Redis, not DynamoDB: `AGUIPipelineRequestHandler` refuses a store
    that cannot stream chunks (`integration/agui/queue_handler.py:82-86`).
- **`tests/test_deployment_identity.py`**
  - Drop the `ECSIOHandler` import (`:29`).
  - `test_the_entry_points_take_no_validator` (`:557-558`) checks `AWSWebsocketAPI.run`'s parameters are
    `["handlers"]`.
  - Add `ECSIOHandler`, `ECSAgentRunner`, `ECSOutputConsumer` and `AWSRestAPI` to `TestRemovedNames`: each is
    not an attribute of `agentkernel.aws`.
- **`tests/test_ecs_sqs_consumer_parallel.py`**: delete `TestECSOutputConsumerRegression` (`:107-116`). It
  imports the deleted class. The rest stays.
- **`tests/test_api_http.py`**: docstrings at `:428`, `:447`, `:541` stop naming `AWSRestAPI`. Assertions don't
  change.

### Deleted tests

Their behaviour is already covered by the pipeline suites:

| Deleted | Pipeline coverage |
|---|---|
| `test_ecs_agent_runner_schedule.py` | `test_pipeline_agent_runner_schedule.py` |
| `test_ecs_akagentrunner_stream.py` | `test_pipeline_agent_runner.py:170`, `:214` (chunk dedup suffix, error chunk) |
| `test_ecs_akagentrunner_realtime.py` | `test_realtime_pool.py:487-529`, `test_pipeline_protocol_routing.py` |
| `test_ecs_akoutputconsumer.py` | `test_pipeline_response_handler.py:168-217` + the new `endpoint_url` tests |
| `test_ecs_output_consumer_status.py` | `test_pipeline_response_handler.py:83-105` |
| `test_ecs_io_handler.py` | `test_ecs_websocket_routes.py` `TestQueueHandOff`, `test_pipeline_io_handler.py` |

### Terraform

`terraform -chdir=ak-deployment/ak-aws/containerized validate`, plus one `terraform plan` with
`queue_mode=true, execution_mode="rest_sync", message_type="delta"` that must fail on the new message. The
module has no `tftest` suite today, so this is a manual check, recorded in the PR.
