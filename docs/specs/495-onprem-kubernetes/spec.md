# #495: Unified queue execution pipeline + on-prem Kubernetes deployment — Implementation Spec

This spec details how the approved `design.md` is built: a new `agentkernel/pipeline/` package
holding the five-component execution pipeline (Request Handler → Input Queue → Agent Runner →
Output Queue → Response Handler) with pluggable queue transports (`in_memory` default, `sqs`,
`kafka`, `nats`), the pod-direct WebSocket delivery path, the response-store relocation with a new
`in_memory` backend, and the `ak-deployment/ak-k8s/` Helm chart. `design.md` is the requirements
source; all line citations verified against `develop` on 2026-08-12.

## Design

### 1. Package layout and coupling

```
ak-py/src/agentkernel/pipeline/
├── __init__.py            # exports: RequestHandler, AgentRunner, StreamAgentRunner,
│                          #   ResponseHandler, IOHandler, QueueTransport, TransportConsumer,
│                          #   QueueMessage, QueueTransportFactory
├── envelope.py            # QueueMessage + attribute-name constants
├── consumer.py            # ConsumerLoop — the generic batch/retry/permanent-failure machinery
├── agent_runner.py        # AgentRunner + StreamAgentRunner
├── response_handler.py    # ResponseHandler
├── request_handler.py     # RequestHandler (REST enqueue/poll/SSE surface)
├── io_handler.py          # IOHandler — single-process and two-process topologies
├── thread_runner.py       # ThreadRunner (moved; shim left behind)
├── response_store/
│   ├── __init__.py
│   ├── base.py            # ResponseStore ABC (moved from deployment/common/response_store.py)
│   ├── handler.py         # ResponseDBHandler factory (moved from deployment/aws/core/response_store/)
│   ├── in_memory.py       # InMemoryResponseStore (new)
│   ├── redis.py / valkey.py / dynamodb.py   # moved unchanged
├── ws/
│   ├── base.py            # WebSocketConnectionStoreABC + WebSocketHandlerABC (moved)
│   ├── registry.py        # LocalConnectionRegistry (pod-local, in-memory)
│   ├── push.py            # PodPushWebSocketHandler (HTTP POST to endpoint_url)
│   ├── handler.py         # PipelineWebSocketHandler (native FastAPI WebSocket route)
│   └── endpoint.py        # internal push endpoint router (+ shared-secret auth)
└── transport/
    ├── __init__.py
    ├── base.py            # QueueTransport / TransportConsumer ABCs + QueueTransportFactory
    ├── in_memory.py       # InMemoryTransport
    ├── sqs.py             # SQSTransport
    ├── kafka.py           # KafkaTransport (+ bookkeeping.py helpers)
    ├── bookkeeping.py     # BookkeepingStore — attempt counts + dedup, follows session config
    └── nats.py            # NatsTransport (+ module-level event-loop thread)
```

Coupling rules (numbered, enforced by import direction):

1. `pipeline` imports `core` and `api` only. `api/handler.py` imports nothing new;
   `api/http.py` imports `pipeline` **lazily inside methods** (same pattern as its existing lazy
   a2a/mcp imports, `api/http.py:105-115`), so no import cycle exists.
2. `deployment/` imports `pipeline`; nothing in `pipeline` imports `deployment`.
3. Moved modules leave **re-export shims** at their old paths so every existing import keeps
   working: `deployment/common/thread_runner.py`, `deployment/common/response_store.py`,
   `deployment/common/websocket_service.py`, and `deployment/aws/core/response_store/`
   (`__init__.py` re-exports `ResponseDBHandler`; `redis/valkey/dynamodb` modules re-export their
   store classes). `deployment/common/__init__.py` (`queue_consumer`/`thread_runner` exports,
   currently 2 lines) keeps exporting `QueueConsumer` and `ThreadRunner`.
4. Transports never read `AKConfig` for connection details at method level — the factory reads
   config once and passes explicit constructor parameters (mirrors the shared-driver rule,
   `core/util/driver/`).

### 2. Message envelope and transport interface (`envelope.py`, `transport/base.py`)

```python
class QueueMessage(BaseModel):
    body: str                          # JSON payload (serialized BaseRunRequest / reply dict)
    attributes: dict[str, str] = {}    # REQUEST_ID, USER_ID, ENDPOINT_URL, STATUS_CODE (constants in envelope.py)
    group_id: Optional[str] = None     # session_id — per-group FIFO key
    dedup_id: Optional[str] = None
    receive_count: int = 1             # 1-based, like SQS ApproximateReceiveCount
    native: Any = None                 # transport-native handle; excluded from model_dump

class QueueName(StrEnum):
    INPUT = "input"; OUTPUT = "output"

class QueueTransport(ABC):             # send side — process-wide, thread-safe
    @abstractmethod
    def send(self, queue: QueueName, message: QueueMessage) -> Any: ...

class TransportConsumer(ABC):          # receive side — ONE INSTANCE PER CONSUMER THREAD
    @abstractmethod
    def fetch(self, batch_size: int, wait_seconds: float) -> list[QueueMessage]: ...
    @abstractmethod
    def ack(self, message: QueueMessage) -> None: ...     # success or handled permanent failure
    def nack(self, message: QueueMessage) -> None: ...    # default no-op: redelivery via timeout
    def close(self) -> None: ...                          # default no-op

class QueueTransportFactory:
    _BUILTIN_TYPES = ("in_memory", "sqs", "kafka", "nats")
    @staticmethod
    def resolve_type() -> str: ...     # queues.type; None → "sqs" if queues.input.url else "in_memory"
    @staticmethod
    def create() -> QueueTransport: ...
    @staticmethod
    def create_consumer(queue: QueueName) -> TransportConsumer: ...
```

- Factory follows the #541 house pattern (`core/util/factory.py`): `if/elif` real imports for
  built-ins, `resolve_dotted` for a dotted-path BYO `QueueTransport` subclass, `require_extra`
  for `kafka`/`nats` import errors, `AKConfigError` for unknown types.
- The concurrency contract: `QueueTransport.send` must be callable from any thread and the
  uvicorn event loop (always dispatched via `asyncio.to_thread` from async code, as
  `rest_handler.py:56` does today); each `TransportConsumer` instance is single-thread-owned.
- `QueueHandler` (`deployment/common/queue_handler.py:7`) is **unchanged** — it remains the
  send-side ABC for the ECS/Lambda legacy path. The pipeline does not implement it; the two meet
  only at the SQS wire format (§6).

### 3. Generic consumer machinery (`consumer.py`)

`ConsumerLoop` is the extraction of `ECSSQSConsumer._process_single/_consumer_loop/run`
(`containerized/core/sqs_consumer.py:107-175`), instance-based:

```python
class ConsumerLoop:
    def __init__(self, queue: QueueName, process: Callable[[QueueMessage], None],
                 on_permanent_failure: Callable[[QueueMessage], None],
                 max_receive_count: int, num_consumers: int, batch_size: int,
                 consumer_factory: Callable[[], TransportConsumer], thread_name_prefix: str): ...
    def run(self) -> None: ...          # blocking; ThreadRunner tasks, graceful=True
    def _consumer_loop(self) -> None: ...
    def _process_single(self, consumer, msg) -> None: ...
```

Behavior, byte-equivalent to the ECS semantics:

1. `run()` starts `num_consumers` `ThreadRunner` tasks (`stop_all_on_failure=True,
   graceful=True`), thread names `f"{prefix}-{i}"`; each thread creates its own
   `TransportConsumer` via `consumer_factory` and loops while
   `not ThreadRunner.shutdown_event.is_set()`.
2. Per message: `receive_count > max_receive_count` → `on_permanent_failure(msg)` (contract
   unchanged: implementations must catch their own exceptions, `queue_consumer.py:39-45`) then
   `ack`; else `process(msg)` then `ack`; `process` raising → log + `nack` (message redelivered
   by the transport's timeout mechanics), matching `sqs_consumer.py:112-130`.
3. `fetch` raising → log + `time.sleep(5)` + continue (matches `sqs_consumer.py:135-140`).
4. `async def process` callables are supported via the same `inspect.iscoroutinefunction` +
   `asyncio.run` dispatch as `sqs_consumer.py:119-123`.

`ECSSQSConsumer` is rebuilt as a thin shim over `ConsumerLoop` with its public surface unchanged:
`max_receive_count`/`num_consumers` class attrs, `get_queue_url`, `poll`, `process_message`,
`on_permanent_failure`, `delete_message`, `_get_client`, `_process_single`, `_consumer_loop`,
`run` all remain classmethods with identical signatures and behavior — `run()` constructs a
`ConsumerLoop` whose `consumer_factory` yields an internal adapter that delegates
`fetch→cls.poll()` (converting raw boto3 records to envelopes with `native=record`),
`ack→cls.delete_message(native)`, and whose callbacks call `cls.process_message(native)` /
`cls.on_permanent_failure(native)` — subclass overrides (`ECSAgentRunner`, `ECSOutputConsumer`,
user subclasses) keep receiving **raw boto3 records**, exactly as today.

### 4. In-memory transport (`transport/in_memory.py`)

Process-wide singleton state (one `_InMemoryQueue` per `QueueName`), `threading.Lock` +
`threading.Condition` per queue:

- **Per-group FIFO**: a `_InMemoryQueue` holds `deque[QueueMessage]` per `group_id` (messages with
  `group_id=None` get a per-message synthetic group). At most one message per group is in flight;
  `fetch` hands out the head of up to `batch_size` distinct groups; `ack` releases the group.
  This reproduces SQS FIFO `perMessageGroupId` semantics (one session in order, sessions in
  parallel).
- **Redelivery**: a fetched message carries a deadline `now + ack_wait` (config, default 30 s); a
  background sweep (piggybacked on `fetch` calls — no dedicated timer thread) returns expired
  in-flight messages to their group head with `receive_count += 1`. Explicit `nack` returns it
  immediately.
- **Dedup**: `send` drops a message whose `dedup_id` was seen within `dedup_window` (default
  300 s, SQS parity); expired entries pruned on `send`.
- **Blocking fetch**: `fetch(batch_size, wait_seconds)` waits on the condition variable up to
  `wait_seconds` — the long-poll equivalent; honors `execution.queues.batch_size` with a local
  default of 1.
- No durability and no size bound (documented; the design's stated boundary).
- `AgentRunner.run()` with `type=in_memory` raises
  `AKConfigError("memory transport runs in-process — start IOHandler instead")` (§8).

### 5. SQS transport (`transport/sqs.py`)

- `send`: delegates to `SQSHandler.send_message` (`aws/core/sqs_handler.py:227`) with
  `message_group_id=group_id`, `message_deduplication_id=dedup_id`, and attributes via
  `SQSHandler.CustomAttribute` — the wire format is **identical** to today's
  `send_message_to_input_queue`/`send_message_to_output_queue` (`sqs_handler.py:309-392`)
  including the standard `request_id`/`user_id` attributes (`:273-295`), so pipeline producers
  and ECS consumers (or vice versa) interoperate during migration.
- `TransportConsumer`: one boto3 client per consumer instance; `fetch` = `receive_message` with
  `MaxNumberOfMessages=batch_size`, `WaitTimeSeconds=wait_seconds`, `AttributeNames=["All"]`,
  `MessageAttributeNames=["All"]` (as `sqs_consumer.py:66-71`); envelope mapping: `body` =
  `record["Body"]`, `attributes` via `SQSHandler.get_message_custom_attributes`
  (`sqs_handler.py:170`), `group_id` from `Attributes.MessageGroupId`, `receive_count` from
  `Attributes.ApproximateReceiveCount`, `native=record`; `ack` = `delete_message(ReceiptHandle)`;
  `nack` = no-op (visibility timeout).
- Queue URLs from the existing `execution.queues.input.url`/`output.url` (`config.py:323,340`).

### 6. Kafka transport (`transport/kafka.py`, `transport/bookkeeping.py`)

Client `confluent-kafka` (new `kafka` extra). Per `research/kafka.md`:

- **Producer** (process-wide singleton): `enable.idempotence=true`; `send` maps `group_id` →
  record key, `attributes` (+ `dedup_id` under key `ak-dedup-id`) → headers, topic from config
  (`input_topic`/`output_topic`).
- **Consumer** (one `confluent_kafka.Consumer` per thread): `group.id` from config,
  `enable.auto.commit=false`, `partition.assignment.strategy=cooperative-sticky`. `fetch` =
  `consume(num_messages=batch_size, timeout=wait_seconds)`.
- **Receive count + dedup — `BookkeepingStore`** (design decision Q5: follows the session
  storage configuration): resolved from `AKConfig.session.type` — `redis`/`valkey` use the shared
  drivers (`core/util/driver/`) with the session block's connection settings and key prefixes
  `ak:qattempts:` / `ak:qdedup:`; `in_memory` (or any other session type) falls back to an
  in-process dict **with a one-time WARNING** that Kafka retry bookkeeping is process-local.
  Surface: `incr_attempts(key) -> int` (TTL 1 h), `clear_attempts(key)`,
  `seen_dedup(dedup_id) -> bool` (SET NX EX 300 semantics).
- **Fetch path**: for each record — dedup header seen → `ack` (commit) and skip;
  `receive_count = incr_attempts(f"{topic}:{partition}:{offset}")`.
- **Ack** = commit offset (per-partition, after the batch's records complete in order) +
  `clear_attempts`. **Nack** = `seek()` back to the record's offset + `pause()` the partition for
  a backoff (default 2 s, config `retry_backoff`), calling `poll(0)` during the pause so the
  consumer stays under `max.poll.interval.ms`; `resume()` then re-fetch — the blocking in-process
  retry pattern. Head-of-line blocking per partition is accepted and documented.
- **Permanent failure**: after the `ConsumerLoop` runs the hook, `ack` additionally produces the
  original record (headers + `ak-error` header) to `f"{topic}{dlq_suffix}"` (default `.dlq`).
- Topics are pre-provisioned (Strimzi CRs / chart); the transport does not create topics.

### 7. NATS JetStream transport (`transport/nats.py`)

Client `nats-py` (new `nats` extra). Per `research/nats-jetstream.md`:

- **Event-loop bridge**: module-level `_NatsLoop` singleton — one daemon thread running
  `loop.run_forever()`; all client coroutines dispatched via
  `asyncio.run_coroutine_threadsafe(...).result(timeout)`. One `nats` connection per process.
- **Subjects/streams**: input `chat.req.<session_id>` on stream `AGENT_REQUESTS` with a
  deterministic-subject-mapping transform to `chat.req.<partition>.<session_id>` (`partitions`
  config, default 32); output symmetric on `AGENT_REPLIES` / `chat.out.*` (spec decision for the
  design's open point: the output path **is** partitioned, same count — per-session chunk order
  needs it and idle partitions are free). Retention `WorkQueuePolicy`, `duplicate_window` 300 s,
  `max_age` 24 h safety net.
- **Send**: `js.publish(subject, body, headers={"Nats-Msg-Id": dedup_id, ...attributes})`.
- **Consumers**: durable pull consumer per partition (`filter_subject="chat.req.<p>.>"`,
  `ack_wait` config default 30 s, `max_deliver = max_receive_count + 1`, `max_ack_pending=1`).
  Each consumer thread cycles the partition consumers in a shuffled order calling
  `fetch(1, timeout=wait_seconds/partitions)`; the server serializes competing fetchers per
  partition. Envelope: `receive_count = msg.metadata.num_delivered`, attributes from headers,
  `group_id` = subject's session token, `native=msg`.
- **Ack** = `msg.ack()`. **Nack** = `msg.nak(delay=retry_backoff)`. **Permanent failure**: after
  the hook, `ack` calls `msg.term()` (removes from the work-queue stream; `max_deliver` is the
  server-side backstop).
- **Provisioning**: `auto_provision: true` (default in `values-dev` and local) creates
  streams/consumers/transforms via the JS management API at startup; `false` (production) only
  verifies and raises `AKConfigError` naming the missing object and pointing at the NACK CRs.

### 8. Pipeline components

**`AgentRunner` / `StreamAgentRunner`** (`agent_runner.py`) — generalized from
`ECSAgentRunner`/`ECSStreamAgentRunner` (`containerized/akagentrunner.py:13,141`):

- `process(msg)`: `BaseRunRequest.model_validate(json.loads(msg.body))`; require
  `REQUEST_ID` attribute (ValueError otherwise, as `akagentrunner.py:62-64`); run
  `ChatService().process_chat_request(req)` (`chat_service.py:434`); send to OUTPUT a
  `QueueMessage(body=json.dumps(response_dict), attributes carried over,
  group_id=session_id, dedup_id=request_id)` — **plus a new `STATUS_CODE` attribute** carrying
  the dropped status (`_, agent_response = ...` drops it today, `akagentrunner.py:110`; §12
  behavioral change 6).
- `StreamAgentRunner.process`: `process_stream_chat_sync` chunk fan-out, one OUTPUT message per
  chunk, `dedup_id = f"{request_dedup}-{receive_count}-{chunk_index}"`
  (`akagentrunner.py:213-220`); `ENDPOINT_URL` required unless the transport is `in_memory`
  (single-process SSE needs no endpoint — relaxation of `akagentrunner.py:170-172`).
- Permanent-failure hooks mirror `akagentrunner.py:121-130` / `:227-246` (error body / error
  chunk to OUTPUT; self-guarded).
- Entry point: `AgentRunner.run()` classmethod — resolves transport type (`in_memory` → raise, §4),
  dispatches to `StreamAgentRunner` when `execution.mode == STREAM` (as `akagentrunner.py:132-138`),
  builds the `ConsumerLoop` from `queues.input.*` config.

**`ResponseHandler`** (`response_handler.py`) — generalized from `ECSOutputConsumer`
(`containerized/akoutputconsumer.py:15`):

- REST modes: write `{"session_id", "request_id", "status_code", "body"}` to the response store
  (`akoutputconsumer.py:144-166` plus the new status field).
- ASYNC/STREAM: push via the configured `WebSocketHandlerABC` — `PodPushWebSocketHandler` on
  k8s/self-hosted, in-process delivery when the transport is `in_memory` (below); message types per
  mode as `akoutputconsumer.py:65-74`.
- STREAM + memory transport: chunks are appended to the `InMemoryResponseStore` stream for the
  request (`add_chunk(request_id, chunk_dict)`) so the SSE generator in the Request Handler can
  drain them — no WS required locally.
- Permanent-failure mirror of `akoutputconsumer.py:85-142` (error entry to store / error frame
  over WS so clients never hang).

**`RequestHandler`** (`request_handler.py`) — extends `RestHandler`
(`deployment/common/rest_handler.py:16`), which stays unchanged except for one new seam:

- `RestHandler` gets `_build_sync_response(record) -> Any` (default: today's
  `response.get("body", response)`, `rest_handler.py:83,127`) so subclasses can honor
  `status_code`. No other change; `ECSQueueRequestHandler` behavior identical.
- `RequestHandler.get_queue_handler()` returns an adapter exposing
  `send_message_to_input_queue(...)` over `QueueTransport.send` (keeps `enqueue_and_wait`
  verbatim); `get_response_store()` uses the relocated `ResponseDBHandler`.
- `_build_sync_response` override: stored `status_code >= 400` → `HTTPException(status_code,
  detail=body)` — restoring today's **direct-mode** error contract
  (`ResponseBuilder.build_response` raises in `rest_api_mode`, `chat_service.py:299-302`) on the
  pipeline path.
- Routes: `AGENTS_PATH` GET, `CHAT_PATH` POST (enqueue; SSE `StreamingResponse` when
  `mode == STREAM` — drains `InMemoryResponseStore.stream(request_id)`), `CHAT_PATH` GET
  (`rest_async` poll), and `CHAT_MULTIPART_PATH` POST **only when the transport is `in_memory`**:
  uploads are read (bounded by `api.max_file_size`, `config.py:101`) and converted to the
  base64 `images`/`files` fields `RequestBuilder.from_base_request_sync` already consumes
  (`chat_service.py:37,75-117`), then enqueued as ordinary JSON. Broker transports keep today's
  ECS behavior (no multipart route, `rest_handler.py:135-144`).
- `mode=None` is treated as `REST_SYNC` on the pipeline path (parity: both return the same
  success dict `{"result", "session_id"}`; errors raise `HTTPException` — §12 change 1).

**`IOHandler`** (`io_handler.py`) — generalized from `ECSIOHandler`
(`containerized/ecs_io_handler.py:10`):

- `IOHandler.run(auth_validator=None)`; topology by transport type:
  - `in_memory` → **single-process**: ThreadRunner tasks = `rest-api` (uvicorn, `graceful=True`,
    `awaited_on_shutdown=False` as `ecs_io_handler.py:50-56`), `response-handler`
    (`ResponseHandler` loop), **and `agent-runner` (`AgentRunner` loop)** — all five components.
  - broker types → **two-process**: `rest-api` + `response-handler` only; `AgentRunner.run()` is
    the second container.
- WS modes (`ASYNC`/`STREAM` over WS): `auth_validator` mandatory (fail-fast as
  `ecs_io_handler.py:32-36`); the REST app additionally mounts `PipelineWebSocketHandler` (§9)
  and the internal push endpoint router.

**`RESTAPI` default wiring** (`api/http.py`): `run()` gains a pipeline delegation guard ahead of
its current body — it lazily imports and delegates to `IOHandler.run()` **only when all three
hold**: `cls is RESTAPI` exactly (subclasses — `AWSRestAPI`, `AWSWebsocketAPI` — keep their own
paths untouched, so ECS never delegates), the caller passed no explicit `handlers`, and
`QueueTransportFactory.resolve_type()` returns `in_memory`. Because `resolve_type()` yields
`in_memory` by default, every existing
`RESTAPI.run()` app boots the single-process pipeline; passing explicit `handlers` (including
`AgentThreadRequestHandler` — Q6: the thread surface stays an inline, IO-side handler in v1)
preserves today's inline path unchanged.

### 9. WebSocket delivery (`ws/`) — pod-direct push (design Q3, Option D)

- **`ws/base.py`**: `WebSocketConnectionStoreABC` + `WebSocketHandlerABC` moved verbatim from
  `deployment/common/websocket_service.py:7,65` (shim left behind; AWS subclasses untouched).
- **`LocalConnectionRegistry`** (`ws/registry.py`): implements `WebSocketConnectionStoreABC`
  over two in-process dicts (`user_id → {connection_id: WebSocket}`, `connection_id → user_id`),
  `threading.Lock`-guarded. No TTL (connections die with the pod).
- **`PipelineWebSocketHandler`** (`ws/handler.py`): a **native FastAPI WebSocket route**
  (`/ws`) — new code; the ECS handlers assume API-Gateway-proxied HTTP frames with `x-ws-*`
  headers (`websocket_api.py:32-34`) and are not reusable here. Lifecycle: accept → authenticate
  `token` query param via the `AuthValidator` (claims must include `userId`, matching
  `websocket_api.py:138-148`) → register in the local registry; frame loop parses
  `BaseRequest.from_payload` (`model.py:225`) and dispatches the chat route (enqueue with
  attributes `REQUEST_ID`, `USER_ID`, `ENDPOINT_URL`) plus custom routes (same
  `register(route)`-style decorator surface as `AWSWebsocketAPI.register`,
  `websocket_api.py:447-469`); disconnect → deregister.
- **`ENDPOINT_URL` value**: `http://{pod_ip}:{api.port}` where `pod_ip` = env `AK_POD_IP`
  (chart-injected via the downward API) → fallback `socket.gethostbyname(socket.gethostname())`
  → `127.0.0.1`. With the `in_memory` transport the sentinel value `local` short-circuits to
  in-process delivery through the registry (no HTTP hop).
- **Internal push endpoint** (`ws/endpoint.py`): `POST /internal/push` with JSON
  `{"user_id", "message", "message_type"}`; auth via header `x-ak-push-token` compared against
  config `websocket_api.push_auth_token` (required whenever the transport is not `in_memory` —
  startup `AKConfigError` otherwise); resolves the user's local connections and writes frames on
  the uvicorn loop via `asyncio.run_coroutine_threadsafe`. Unknown user/no connections → 404
  (the k8s `GoneException` analogue).
- **`PodPushWebSocketHandler`** (`ws/push.py`): implements `WebSocketHandlerABC.send` as the
  HTTP POST above (connection pooling via a module-level `httpx.Client`); 404/connection-refused
  → log + raise so the `ConsumerLoop` retry/permanent-failure semantics apply
  (`max_receive_count` retries, then the error is dropped with a warning — bounded, never
  crash-looping).
- Semantic difference recorded (design R6): replies reach the user's connections on the
  originating pod only.

### 10. Response store changes (`pipeline/response_store/`)

- `ResponseStore` ABC, `ResponseDBHandler`, and the Redis/Valkey/DynamoDB stores move unchanged
  (shims at old paths, §1 rule 3). `ResponseDBHandler.Type` (`handler.py:16`) gains `MEMORY`;
  `_ResponseStoreConfig.type` pattern (`config.py:314`) becomes
  `^(in_memory|redis|valkey|dynamodb)$`.
- **Resolution default**: `execution.response_store is None` + transport `in_memory` → in_memory store
  (today's constructor raises `ValueError`, `handler.py:50-51`; that error is preserved for
  broker transports without a configured store).
- **`InMemoryResponseStore`**: process-wide dict of `request_id → queue.Queue` +
  `threading.Event`-based waiters. `add_message(record)` honors the standard record shape;
  `get_message(request_id, get_and_delete)` returns `record["body"]` — matching the existing
  stores' contract (`response_store/redis.py:28`, `dynamodb.py:25`) — but also keeps the full
  record so `RequestHandler._build_sync_response` can read `status_code`; `add_chunk`/`stream`
  support the SSE path (§8). `get_message_with_retry` is inherited unchanged
  (`response_store.py:37-74`).
- **Fail-fast rule** (design R6): at `IOHandler`/`RequestHandler` startup, transport ≠ `in_memory`
  **and** response store type == `in_memory` (or defaulted) in a REST mode → `AKConfigError`
  ("multi-process queue modes need a shared response store").

### 11. Config changes (`core/config.py`)

```python
class _InMemoryQueueConfig(BaseModel):
    ack_wait: float = 30.0
    dedup_window: float = 300.0

class _KafkaQueueConfig(BaseModel):
    bootstrap_servers: str = "localhost:9092"
    input_topic: str = "agent-input"; output_topic: str = "agent-output"
    group_id: str = "agent-kernel"; dlq_suffix: str = ".dlq"
    retry_backoff: float = 2.0
    client_config: dict[str, Any] = {}      # passthrough to confluent-kafka (SASL/TLS etc.)

class _NatsQueueConfig(BaseModel):
    url: str = "nats://localhost:4222"
    input_stream: str = "AGENT_REQUESTS"; input_subject_prefix: str = "chat.req"
    output_stream: str = "AGENT_REPLIES"; output_subject_prefix: str = "chat.out"
    partitions: int = 32
    ack_wait: float = 30.0; retry_backoff: float = 2.0
    auto_provision: bool = False

class _QueuesConfig(BaseModel):             # config.py:356 — extended
    type: Optional[str] = None              # in_memory|sqs|kafka|nats|<dotted>; None → resolve_type()
    input: _InputQueueConfig = ...          # unchanged (url stays SQS-specific)
    output: _OutputQueueConfig = ...        # unchanged
    batch_size: Optional[int] = ...         # unchanged
    memory: Optional[_InMemoryQueueConfig] = None
    kafka: Optional[_KafkaQueueConfig] = None
    nats: Optional[_NatsQueueConfig] = None
```

- `_WebSocketAPIConfig` (`config.py:104-107`) gains `push_auth_token: Optional[str] = None` and
  `push_port: Optional[int] = None` (defaults to `api.port`).
- Field descriptions updated to drop "SQS" where the field is now backend-neutral
  (`_QueuesConfig.input/output` descriptions, `config.py:357-358`); `url` descriptions state
  "SQS only".
- **Compatibility**: existing YAML/`AK_*` env vars are untouched — `type` absent + `url` present
  resolves to `sqs` (§2), absent both → `in_memory`. `max_receive_count`, `no_of_consumers`,
  `batch_size` apply to every transport. Data compatibility: response-store records written
  before this change lack `status_code`; readers treat absence as 200 (today's behavior).
- `pyproject.toml` gains extras `kafka = ["confluent-kafka>=2.15.0"]`,
  `nats = ["nats-py>=2.15.0"]` (pattern of `redis`/`valkey`, `pyproject.toml:67-73`).

### 12. Behavioural changes (all intentional)

1. **Default REST server path becomes the in-process pipeline** (`RESTAPI.run()` with no
   handlers): requests flow enqueue → runner thread → response store instead of inline
   `await`. Wire parity is preserved: success `{"result", "session_id"}` and
   `HTTPException(status, detail={"error", "session_id"})` exactly as `ResponseBuilder`
   produces today; SSE framing unchanged (`stream_chunk`, `chat_service.py:306-318`). Added
   latency is in-process queue hops.
2. `execution.queues.type` exists; untyped configs resolve exactly as today (`url` ⇒ `sqs`).
3. `/api/v1/chat` GET (`rest_async` poll) becomes available on the local pipeline (was
   ECS-queue-mode-only).
4. `/api/v1/chat-multipart` works in queue mode **on the in_memory transport** (was unavailable in
   any queue mode; still unavailable on broker transports).
5. `mode=None` runs as `REST_SYNC` through the pipeline (same wire shapes as the old inline
   path).
6. Output messages and response-store records now carry `status_code`; the **pipeline** REST
   surface maps stored errors to `HTTPException` (the ECS path keeps returning error bodies with
   HTTP 200 — its today's behavior, unchanged).
7. `ECSSQSConsumer` internals delegate to `ConsumerLoop`; its public classmethod surface,
   record shapes, log messages, and retry semantics are unchanged.
8. New native `/ws` WebSocket endpoint + `/internal/push` endpoint exist only when `IOHandler`
   runs in a WS mode (ASYNC/STREAM outside AWS API Gateway deployments).
9. The thread surface (`AgentThreadRequestHandler`) stays inline (IO-side) in v1: mounting it
   explicitly bypasses pipeline delegation (§8), so thread recording semantics are unchanged.

**Non-changes**: ECS and Lambda wire behavior, entry points, and exports
(`deployment/aws/__init__.py` lazy-export table unchanged); `SQSHandler` and `QueueHandler`
surfaces; SQS FIFO group/dedup mapping; session/thread/multimodal stores; CLI, A2A, MCP
(`AgentService` direct); Azure/GCP deployments; `AgentRESTRequestHandler` routes and shapes when
explicitly instantiated.

### 13. Helm chart (`ak-deployment/ak-k8s/`)

```
ak-deployment/ak-k8s/
├── README.md
├── chart/
│   ├── Chart.yaml                 # apiVersion v2; dependencies: valkey (valkey-io/valkey-helm,
│   │                              #   condition valkey.enabled), nats (nats-io, condition nats.enabled)
│   ├── values.yaml                # neutral defaults (transport: nats, gateway disabled, dev-ish)
│   ├── values-baremetal.yaml      # gatewayClassName envoy-gateway, MetalLB note, cert-manager
│   │                              #   issuer annotations, storageClassName openebs-hostpath
│   ├── values-eks.yaml            # ALB/NLB gateway classes, EBS gp3, Pod Identity; sqs|kafka|nats
│   ├── values-dev.yaml            # single replicas, auto_provision nats, TLS off, in_memory response
│   │                              #   store only for single-pod profile
│   └── templates/
│       ├── _helpers.tpl
│       ├── deployment-io.yaml         # io-handler: IOHandler.run entrypoint; AK_POD_IP downward API
│       ├── deployment-agent-runner.yaml
│       ├── service.yaml               # ClusterIP for io-handler (+ push port)
│       ├── gateway.yaml / httproute.yaml   # Gateway API Standard; WS route with raised timeouts,
│       │                                    #   no request buffering; enabled: gateway.enabled
│       ├── service-lb.yaml            # fallback Service type=LoadBalancer (gateway.enabled=false)
│       ├── secret-push-token.yaml     # websocket push shared secret
│       ├── networkpolicy.yaml         # /internal/push reachable only from app pods
│       ├── configmap-env.yaml         # AK_* env injection (table below)
│       ├── scaledobject.yaml          # KEDA; scaler chosen by transport (kafka lag / nats pending)
│       ├── servicemonitor.yaml        # optional
│       ├── nats-resources.yaml        # NACK Stream/Consumer CRs (incl. subject transform,
│       │                              #   duplicate_window, max_deliver) — nats.enabled
│       └── kafka-cluster.yaml         # Strimzi Kafka/KafkaNodePool/KafkaTopic CRs — kafka.enabled
└── ci/                            # chart-testing config + kind smoke values
```

- **Env-var contract** (the ECS Terraform split preserved — app config declares modes, infra
  injects connections): `AK_EXECUTION__MODE`, `AK_EXECUTION__QUEUES__TYPE`,
  `AK_EXECUTION__QUEUES__{KAFKA,NATS}__*` connection values, `AK_EXECUTION__QUEUES__BATCH_SIZE`,
  `AK_EXECUTION__RESPONSE_STORE__*`, `AK_SESSION__*` → in-cluster Valkey,
  `AK_WEBSOCKET_API__PUSH_AUTH_TOKEN` (secretRef), `AK_POD_IP` (fieldRef `status.podIP`).
- All images behind `global.imageRegistry`; a `docs/images.txt` manifest generated per release.
- KEDA `ScaledObject` targets the agent-runner Deployment; `minReplicaCount: 1`;
  `maxReplicaCount` default derived as `partitions // input.no_of_consumers`; NATS scaler
  monitoring endpoint = the NATS headless service `:8222`.
- Agent-runner `terminationGracePeriodSeconds: 120` default + SIGTERM handler note (consumers
  observe `ThreadRunner.shutdown_event`; a `preStop` sleep covers endpoint deregistration).
- Prerequisites documented in README, never installed: Gateway API CRDs + implementation,
  MetalLB (baremetal), cert-manager, KEDA, Strimzi (Kafka), NACK (NATS CRs).
- Publishing: chart pushed as an OCI artifact by a new `publish-chart` job (added to the
  release workflow alongside `.github/workflows/sync-terraform.yaml`'s module publishing).

### 14. Example (`examples/k8s/openai-queue-mode/`)

Mirrors `examples/aws-containerized/openai-stream-queue-mode/` (two entry files, two
Dockerfiles): `app_io_handler.py` (`from agentkernel.pipeline import IOHandler`;
`IOHandler.run(auth_validator=...)` in WS modes) and `app_agent_runner.py`
(`from agentkernel.pipeline import AgentRunner`; registers the `OpenAIModule`), `config.yaml`
variants (`config.nats.yaml`, `config.kafka.yaml`), helm-install README covering k3d (macOS),
microk8s (native Ubuntu; `metallb`/`hostpath-storage`/`registry` addons), and k3s parity.

### 15. Observability recipes and docs surfaces (design R11, R13)

- Observability ships as documentation + example values (decided): `ak-deployment/ak-k8s/README.md`
  gains an "Observability" section with upstream `helm install` recipes (kube-prometheus-stack,
  OTel collector wiring for the existing Langfuse/OpenLLMetry/Logfire providers, broker exporter
  flags — `promExporter.enabled` for NATS, Strimzi `metricsConfig` + Kafka Exporter for Kafka)
  and a pointer to self-hosted Langfuse v3 (`langfuse/langfuse-k8s`) with its footprint stated.
  Nothing is added to `Chart.yaml` dependencies for observability.
- Docs surfaces (detailed ordering in `plan.md`): `docs/sidebars.js:61-90` gains the On-Prem /
  Kubernetes deployment category; `docs/docs/advanced/queue-mode-guide.md` is re-framed around
  the pipeline + transport matrix (status table at `:353` gains transports and the K8s column);
  `docs/docs/deployment/overview.md` gains the flavor section; dev skills:
  `ak-dev-architecture` (pipeline section) and a new `ak-dev-new-queue-transport` skill.

## Error handling

| Failure | Surface | Behavior |
|---|---|---|
| Unknown `queues.type` | factory | `AKConfigError` listing built-ins + dotted-path option |
| `kafka`/`nats` extra missing | factory | `require_extra` ImportError with `pip install agentkernel[kafka|nats]` |
| Broker unreachable at send | Request Handler | exception → existing 500 mapping (`rest_handler.py:94-96`) |
| Broker unreachable in consumer | ConsumerLoop | log + 5 s sleep + retry (never exits) |
| `in_memory` transport + `AgentRunner.run()` | entrypoint | `AKConfigError` (§4) |
| Broker transport + in_memory/absent response store (REST modes) | IOHandler startup | `AKConfigError` (§10) |
| WS mode without `push_auth_token` (broker transport) | IOHandler startup | `AKConfigError` (§9) |
| Push to stale pod (404/refused) | ResponseHandler | raise → bounded queue retry → permanent-failure drop + warning |
| `max_receive_count` exceeded (input) | AgentRunner hook | error body/chunk to OUTPUT (self-guarded), then ack |
| `max_receive_count` exceeded (output) | ResponseHandler hook | error record to store / error frame over WS, then ack |
| NATS objects missing, `auto_provision: false` | transport init | `AKConfigError` naming stream/consumer + NACK pointer |
| Poison message crash-loop (Kafka) | bookkeeping | attempt count survives restarts on redis/valkey session config; process-local + WARNING otherwise |

## Testing

New test files (patterns per `ak-dev-testing-conventions`: `DummyAgent`/`DummyRunner`,
`monkeypatch` on `AKConfig.get`, `ThreadRunner.shutdown_event.clear()` autouse fixture as in
`ak-py/tests/test_thread_runner.py`):

- `test_pipeline_in_memory_transport.py` — per-group FIFO under concurrent fetch, ack_wait
  redelivery + receive_count increment, dedup window drop, blocking fetch timeout.
- `test_pipeline_consumer_loop.py` — process/ack ordering, nack-on-raise, permanent-failure
  path (hook then ack), poll-exception 5 s retry, shutdown via `shutdown_event`, async
  `process` dispatch.
- `test_transport_contract.py` — a reusable `QueueTransportContract` (the
  `SandboxProviderContract` pattern, `sandbox/testing.py`) asserting the six queue-semantics
  requirements from `research/current-queue-mode.md`; run against `in_memory` in-repo; `sqs` via
  mocked boto3; the same class is reused by integration CI against real Kafka/NATS containers.
- `test_pipeline_sqs_transport.py` — envelope mapping from boto3 records, send-side kwargs
  equality with `SQSHandler.build_send_message_kwargs` output.
- `test_pipeline_kafka_transport.py` — faked `confluent_kafka.Consumer/Producer`: header/key
  mapping, commit-after-ack, seek+pause on nack, DLQ produce on permanent failure, bookkeeping
  fallback WARNING when session type is in_memory.
- `test_pipeline_nats_transport.py` — faked `nats` client on a real `_NatsLoop`: subject
  construction, `Nats-Msg-Id`, `num_delivered` mapping, `term()` on permanent failure,
  `auto_provision=false` verification error.
- `test_pipeline_agent_runner.py` / `test_pipeline_response_handler.py` — mirror the assertions
  of `test_akagentrunner_stream.py`/`test_akresponsehandler.py` on the generalized classes,
  including `STATUS_CODE` propagation and the in_memory-STREAM chunk path.
- `test_pipeline_request_handler.py` — FastAPI `TestClient` over the single-process pipeline:
  `rest_sync` parity (success dict + HTTPException on stored error), `rest_async`
  accept/poll, SSE streaming end-to-end, multipart-on-in_memory, multipart-absent on broker
  transports (mocked).
- `test_pipeline_ws.py` — native `/ws` route (auth, registry lifecycle), `/internal/push`
  (token auth, 404 on unknown user, frame delivery), `PodPushWebSocketHandler` retry-on-404.
- `test_response_store_in_memory.py` — record shape (`get_message` returns `body`), status_code
  retention, chunk streaming, `get_message_with_retry` inheritance.

Existing tests — the riskiest consumer is `ECSSQSConsumer` (its internals move):
`test_ecs_sqs_consumer_parallel.py` must pass **unmodified** — it imports and patches the class
surface directly (`tests/test_ecs_sqs_consumer_parallel.py:5`, classmethod seams `poll`,
`process_message`, `delete_message`, `_get_client`), which the shim preserves. `test_sqs_handler.py`,
`test_akagentrunner_stream.py`, `test_akresponsehandler.py`, `test_thread_runner.py` (import path
via the `deployment/common` shim), and `test_api_http.py` (explicit-handler instantiation)
must pass unmodified; `test_api_http.py` gains one case asserting `RESTAPI.run()` delegates to
`IOHandler` when unconfigured (mocked, no server start).

Run: `cd ak-py && uv run pytest`. Chart CI: `ct lint` + kind install smoke per flavor values
file with one end-to-end chat request through the NATS transport.
