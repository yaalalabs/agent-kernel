# #495: Unified queue execution pipeline + on-prem Kubernetes deployment (Implementation Spec)

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
├── consumer.py            # ConsumerLoop: the generic batch/retry/permanent-failure machinery
├── agent_runner.py        # AgentRunner + StreamAgentRunner
├── response_handler.py    # ResponseHandler
├── request_handler.py     # RequestHandler (REST enqueue/poll/SSE surface)
├── io_handler.py          # IOHandler: single-process and two-process topologies
├── thread_runner.py       # ThreadRunner (moved; shim left behind)
├── testing.py             # QueueTransportContract: reusable transport conformance suite
├── response_store/
│   ├── __init__.py
│   ├── base.py            # ResponseStore ABC (moved from deployment/common/response_store.py)
│   ├── factory.py         # ResponseStoreFactory (#541 pattern; owns the pipeline resolution defaults)
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
    ├── bookkeeping.py     # BookkeepingStore: attempt counts + dedup, follows session config
    └── nats.py            # NatsTransport (+ module-level event-loop thread)
```

Coupling rules (numbered, enforced by import direction):

1. `pipeline` imports `core` and `api` only. `api/handler.py` imports nothing new;
   `api/http.py` imports `pipeline` **lazily inside methods** (same pattern as its existing lazy
   a2a/mcp imports, `api/http.py:105-115`), so no import cycle exists.
2. `deployment/` imports `pipeline`; nothing in `pipeline` imports `deployment`. The SQS
   wire-format primitives (attribute models, `send_message` kwargs assembly, record-attribute
   flatteners) live in `transport/sqs.py`; `SQSHandler` imports them and delegates, with its
   nested classes (`CustomAttribute`, `AttributeDataType`, `SQSQueueInputMessage`) aliasing the
   relocated models so its public surface, isinstance checks, and patch targets are unchanged
   (the same relocation-with-delegation pattern as `ECSSQSConsumer` → `ConsumerLoop`).
3. Moved modules leave **re-export shims** at their old paths so every existing import keeps
   working: `deployment/common/thread_runner.py`, `deployment/common/response_store.py`,
   `deployment/common/websocket_service.py`, and `deployment/aws/core/response_store/`
   (`__init__.py` re-exports `ResponseStoreFactory`; `redis/valkey/dynamodb` modules re-export their
   store classes). `deployment/common/__init__.py` keeps exporting `ThreadRunner` (its
   `QueueConsumer` export is removed by the public-interface cleanup, §12 change 12).
4. Transports never read `AKConfig` for connection details at method level: the factory reads
   config once and passes explicit constructor parameters (mirrors the shared-driver rule,
   `core/util/driver/`).

### 2. Message envelope and transport interface (`envelope.py`, `transport/base.py`)

```python
class QueueMessage(BaseModel):
    body: str                          # JSON payload (serialized BaseRunRequest / reply dict)
    attributes: dict[str, str] = {}    # REQUEST_ID, USER_ID, ENDPOINT_URL, STATUS_CODE (constants in envelope.py)
    group_id: Optional[str] = None     # session_id: per-group FIFO key
    dedup_id: Optional[str] = None
    receive_count: int = 1             # 1-based, like SQS ApproximateReceiveCount
    message_id: Optional[str] = None   # broker message identity, logging only (SQS MessageId, NATS seq, …)
    native: Any = None                 # transport-native handle; excluded from model_dump

class QueueName(StrEnum):
    INPUT = "input"; OUTPUT = "output"

class QueueTransport(ABC):             # send side: process-wide, thread-safe
    @abstractmethod
    def send(self, queue: QueueName, message: QueueMessage) -> Any: ...
    def create_consumer(self, queue: QueueName) -> "TransportConsumer": ...
    # ^ consumer creation hook: built-ins and BYO subclasses override; base raises
    #   NotImplementedError so a send-only transport fails loudly on the receive side

class TransportConsumer(ABC):          # receive side: ONE INSTANCE PER CONSUMER THREAD
    @abstractmethod
    def fetch(self, batch_size: int, wait_seconds: float) -> list[QueueMessage]: ...
    @abstractmethod
    def ack(self, message: QueueMessage) -> None: ...     # success or handled permanent failure
    def nack(self, message: QueueMessage) -> None: ...    # default no-op: redelivery via timeout
    def dead_letter(self, message: QueueMessage) -> None: ...  # terminal disposition after the
    #   permanent-failure hook; default acks (SQS/in_memory), Kafka routes to its DLQ topic first,
    #   NATS will term(). Keeps DLQ routing out of ack, which cannot tell the two paths apart.
    def close(self) -> None: ...                          # default no-op
    fetch_wait_slice_seconds: Optional[float] = None       # cap on one fetch's block (§3 rule 5)

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
- **This transport interface is the only public queue API** (public-interface cleanup, §12
  change 12): producers name a logical queue (`QueueName`) and send an envelope; configuration
  resolves the backend and physical queue. The old deployment-side contracts are removed or
  internalized: the `QueueHandler` ABC is deleted (its `QueueMessageBody`/
  `SendMessageAttributes` models fold into `SQSHandler`, which becomes AWS-adapter-internal
  glue over the same wire format), and `QueueConsumer` is renamed `RawQueueConsumer` and moved
  to `deployment/aws/core/raw_queue_consumer.py` as the internal raw-record base of
  `LambdaSQSConsumer`/`ECSSQSConsumer`.

### 3. Generic consumer machinery (`consumer.py`)

`ConsumerLoop` is the extraction of `ECSSQSConsumer._process_single/_consumer_loop/run`
(`containerized/core/sqs_consumer.py:107-175`), instance-based:

```python
class ConsumerLoop:
    def __init__(self, *, process: Callable[[QueueMessage], None],
                 on_permanent_failure: Callable[[QueueMessage], None],
                 max_receive_count: int, num_consumers: int, batch_size: int,
                 consumer_factory: Callable[[], TransportConsumer], thread_name_prefix: str,
                 queue: Optional[QueueName] = None,     # logging label only
                 wait_seconds: float = 20.0,
                 logger: Optional[logging.Logger] = None): ...
                 # logger override keeps legacy consumers' logger names (ak.ecs.*) and their
                 # exact log-message texts intact through the delegation
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
5. Long fetch waits are sliced to ≤1 s per call so `shutdown_event` is observed promptly (a
   signal-initiated drain must not stall for a full long-poll interval). A consumer whose long
   polls are expensive to slice lifts the cap by declaring
   `TransportConsumer.fetch_wait_slice_seconds` (default `None` = the loop's 1 s slicing): the
   SQS consumer declares 20 s, since SQS bills every receive call and 1 s slices would multiply
   the empty-poll API cost ~20x, accepting a drain that may wait one full poll (within the 30 s
   default stop grace periods on ECS and Kubernetes).

`ECSSQSConsumer` is rebuilt as a thin shim over `ConsumerLoop` with its public surface unchanged:
`max_receive_count`/`num_consumers` class attrs, `get_queue_url`, `poll`, `process_message`,
`on_permanent_failure`, `delete_message`, `_get_client`, `_process_single`, `_consumer_loop`,
`run` all remain classmethods with identical signatures and behavior: `run()` constructs a
`ConsumerLoop` whose `consumer_factory` yields an internal adapter that delegates
`fetch→cls.poll()` (converting raw boto3 records to envelopes with `native=record`),
`ack→cls.delete_message(native)`, and whose callbacks call `cls.process_message(native)` /
`cls.on_permanent_failure(native)`: subclass overrides (`ECSAgentRunner`, `ECSOutputConsumer`,
user subclasses) keep receiving **raw boto3 records**, exactly as today.

### 4. In-memory transport (`transport/in_memory.py`)

Process-wide singleton state (one `_InMemoryQueue` per `QueueName`), `threading.Lock` +
`threading.Condition` per queue:

- **Per-group FIFO**: a `_InMemoryQueue` holds `deque[QueueMessage]` per `group_id` (messages with
  `group_id=None` get a per-message synthetic group). At most one message per group is in flight;
  `fetch` hands out the head of up to `batch_size` distinct groups; `ack` releases the group.
  This reproduces SQS FIFO `perMessageGroupId` semantics (one session in order, sessions in
  parallel).
- **Redelivery**: a fetched message carries a deadline `now + ack_wait` (config, default 300 s:
  in-process redelivery rescues stuck worker threads, and process death loses the queues anyway,
  so the default sits above typical long agent runs rather than at SQS's 30 s); a
  background sweep (piggybacked on `fetch` calls: no dedicated timer thread) returns expired
  in-flight messages to their group head with `receive_count += 1`. Explicit `nack` returns it
  immediately.
- **Dedup**: `send` drops a message whose `dedup_id` was seen within `dedup_window` (default
  300 s, SQS parity); expired entries pruned on `send`.
- **Blocking fetch**: `fetch(batch_size, wait_seconds)` waits on the condition variable up to
  `wait_seconds`: the long-poll equivalent; honors `execution.queues.batch_size` with a local
  default of 1.
- No durability and no size bound (documented; the design's stated boundary).
- `AgentRunner.run()` with `type=in_memory` raises
  `AKConfigError("memory transport runs in-process: start IOHandler instead")` (§8).

### 5. SQS transport (`transport/sqs.py`)

- The SQS wire-format primitives are relocated **into** this module (§1 rule 2):
  `AttributeDataType`, `CustomAttribute`, `SQSQueueInputMessage`, `serialize_message_body`,
  `build_message_attribute(s)`, `build_send_message_kwargs`, and the
  `get_message_system_attributes`/`get_message_custom_attributes` flatteners; `SQSHandler`
  delegates to them with an unchanged public surface.
- `send`: builds kwargs via the shared `build_send_message_kwargs` with
  `message_group_id=group_id`, `message_deduplication_id=dedup_id`, and envelope attributes as
  String `CustomAttribute`s, sent on the transport's own lazily created boto3 client: the wire
  format is **identical by construction** to today's
  `send_message_to_input_queue`/`send_message_to_output_queue` (`sqs_handler.py`) including the
  standard `request_id`/`user_id` attributes, so pipeline producers and ECS consumers (or vice
  versa) interoperate during migration.
- `TransportConsumer`: one boto3 client per consumer instance; `fetch` = `receive_message` with
  `MaxNumberOfMessages=batch_size`, `WaitTimeSeconds=int(min(wait_seconds, 20))` (boto3 requires
  an integer; SQS caps long polls at 20 s), `AttributeNames=["All"]`,
  `MessageAttributeNames=["All"]` (as `sqs_consumer.py:66-71`); envelope mapping: `body` =
  `record["Body"]`, `attributes` via `SQSHandler.get_message_custom_attributes`
  (`sqs_handler.py:170`), `group_id` from `Attributes.MessageGroupId`, `receive_count` from
  `Attributes.ApproximateReceiveCount`, `native=record`; `ack` = `delete_message(ReceiptHandle)`;
  `nack` = no-op (visibility timeout). Declares `fetch_wait_slice_seconds = 20` so the
  `ConsumerLoop` issues one full-length long poll instead of 1 s slices (§3 rule 5).
- Queue URLs from the existing `execution.queues.input.url`/`output.url` (`config.py:323,340`);
  both are required: the factory raises `AKConfigError` when either is missing.

### 6. Kafka transport (`transport/kafka.py`, `transport/bookkeeping.py`)

Client `confluent-kafka` (new `kafka` extra). Per `research/kafka.md`:

- **Producer** (process-wide, one per broker configuration; class-level cache keyed by the
  resolved producer config, `reset()` for tests): `enable.idempotence=true`; `send` maps
  `group_id` → record key, `attributes` (+ `dedup_id` under header `ak-dedup-id`) → headers,
  topic from config (`input_topic`/`output_topic`). The send **waits for the broker
  acknowledgement** (delivery callback polled up to `delivery_timeout`, default 30 s) and raises
  on error or timeout, so an unreachable broker fails the request rather than silently dropping
  the message (error table); it returns `{"MessageId": "topic:partition:offset"}` for the
  Request Handler's enqueue log.
- **Consumer** (one `confluent_kafka.Consumer` per thread): `group.id` =
  `f"{group_id}-{queue}"` so input and output offsets/rebalances stay independent,
  `enable.auto.commit=false`, `auto.offset.reset=earliest`,
  `partition.assignment.strategy=cooperative-sticky`, and
  **`max.poll.interval.ms=900000`** (an LLM-bound agent turn easily exceeds librdkafka's 5 min
  default, which would evict the consumer mid-run); `client_config` merges over all of it for
  SASL/TLS/tuning. `fetch` = `consume(num_messages=batch_size, timeout=wait_seconds)`.
- **Parallelism is per consumer thread, capped by partitions**: Kafka gives a partition to at
  most one group member and a consumer thread processes messages one at a time, so sessions whose
  keys hash to the same partition are handled one after another (SQS FIFO, by contrast, runs a
  queue's distinct groups concurrently). Concurrency therefore equals the number of consumer
  threads holding partitions: `no_of_consumers x replicas` must stay <= the partition count, and
  `QueueTransport.check_consumer_capacity(queue, num_consumers)` (new optional hook, default
  no-op; called from `AgentRunner.start`/`ResponseHandler.start`) reads cluster metadata once per
  process per topic and warns when partitions are fewer than the configured consumers, when the
  queue topic is missing, and when the topic's **dead-letter topic** is missing (a permanently
  failed record commits either way, so an absent DLQ silently discards the only surviving copy);
  it logs the ratio otherwise. One unfiltered metadata call covers the queue and its DLQ, which
  also avoids nudging a broker with auto-creation enabled into creating either. Metadata failures
  are ignored: a startup check never blocks startup.
- **One record in flight per partition**: the consumer buffers a fetched batch per partition and
  hands out at most one record per partition, releasing the next only on `ack`. Required so a
  retry can redeliver a record before any later offset in that partition is committed. This costs
  no throughput (the `ConsumerLoop` processes a batch sequentially anyway); it only turns one
  batch into several buffer-served fetches with no broker round trip.
- **Rebalance handling**: `subscribe` registers `on_revoke`/`on_lost` callbacks that drop buffered
  and in-flight records for partitions this consumer no longer owns; without them, locally
  buffered records would be processed here *and* by the partition's new owner. The callbacks
  commit nothing (uncommitted work is meant to be redelivered) and never reassign partitions, so
  librdkafka's default cooperative handling applies. A **failed commit** (lost partition after a
  rebalance or an eviction during a long turn, or a briefly unreachable broker) is logged and the
  record is released rather than retried locally: processing already succeeded, and the
  uncommitted offset means whoever owns the partition next redelivers it.
- **Receive count + dedup: `BookkeepingStore`** (design decision Q5: follows the session
  storage configuration) built by `BookkeepingStoreFactory`: `redis`/`valkey` session types use
  the shared drivers (`core/util/driver/`) with the session block's connection settings and key
  prefixes `ak:qattempts:` (TTL 1 h) / `ak:qdedup:` (TTL 300 s); every other session type falls
  back to process-local dicts **with a one-time WARNING** naming the consequence (counts reset on
  restart, so a message that crashes its worker can evade the permanent-failure path). Surface:
  `incr_attempts(key) -> int`, `clear_attempts(key)`, and
  **`claim_dedup(dedup_id, owner) -> bool`**: the claim is keyed by the claiming record's
  `topic:partition:offset`, so the owner may reclaim it. A plain `seen_dedup` flag would make a
  record's own retry look like a duplicate and silently drop it. The claim id is **scoped to the
  topic** (`f"{topic}:{dedup_id}"`), matching SQS, whose dedup window is per queue: a reply
  carries the same dedup id as its request (`AgentRunner` forwards it), so a global namespace
  made the input queue's claim swallow every reply on the output queue and every `rest_sync`
  caller timed out. Found by running the contract against a real broker; the fake-backed unit
  tests had not crossed the two queues. The shared Redis/Valkey driver
  gains `incr(key)` (applies the configured TTL on creation only, so a hot counter cannot live
  forever).
- **Fetch path**: for each record: another owner already claimed its `dedup_id` → commit and skip;
  otherwise `receive_count = incr_attempts(f"{topic}:{partition}:{offset}")`.
- **Ack** = commit the record's offset (synchronous) + `clear_attempts`, releasing its partition.
  **Nack** = requeue the record at its partition's buffer head and sleep `retry_backoff`
  (default 2 s): the offset is never committed, so a crash mid-retry leaves the record for
  another group member, and no `seek`/`pause`/`resume` dance is needed (the buffer already holds
  it, and the one-in-flight rule stops later offsets from overtaking it).
- **Permanent failure**: `ConsumerLoop` calls the transport's `dead_letter` disposition after the
  component hook (§2); Kafka's produces the original record (headers + `ak-error`) to
  `f"{topic}{dlq_suffix}"` (default `.dlq`) and then commits. A failed DLQ write is logged and
  the record still commits, since the hook has already answered the caller and an uncommitted
  poison record would replay forever.
- Topics are pre-provisioned (Strimzi CRs / chart); the transport does not create topics.

### 7. NATS JetStream transport (`transport/nats.py`)

Client `nats-py` (new `nats` extra). Per `research/nats-jetstream.md`:

- **Event-loop bridge**: module-level `_NatsLoop` singleton: one daemon thread running
  `loop.run_forever()`; all client coroutines dispatched via
  `asyncio.run_coroutine_threadsafe(...).result(timeout)`. One `nats` connection per process.
- **Subjects/streams**: input `chat.req.<session_id>` on stream `AGENT_REQUESTS` with a
  deterministic-subject-mapping transform to `chat.req.<partition>.<session_id>` (`partitions`
  config, default 32); output symmetric on `AGENT_REPLIES` / `chat.out.*` (spec decision for the
  design's open point: the output path **is** partitioned, same count: per-session chunk order
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

**`AgentRunner` / `StreamAgentRunner`** (`agent_runner.py`): generalized from
`ECSAgentRunner`/`ECSStreamAgentRunner` (`containerized/akagentrunner.py:13,141`):

- `process(msg)`: `BaseRunRequest.model_validate(json.loads(msg.body))`; require
  `REQUEST_ID` attribute (ValueError otherwise, as `akagentrunner.py:62-64`); run
  `ChatService().process_chat_request(req)` (`chat_service.py:434`); send to OUTPUT a
  `QueueMessage(body=json.dumps(response_dict), attributes carried over,
  group_id=session_id, dedup_id=request_id)`: **plus a new `STATUS_CODE` attribute** carrying
  the dropped status (`_, agent_response = ...` drops it today, `akagentrunner.py:110`; §12
  behavioral change 6).
- `StreamAgentRunner.process`: `process_stream_chat_sync` chunk fan-out, one OUTPUT message per
  chunk, `dedup_id = f"{request_dedup}-{receive_count}-{chunk_index}"`
  (`akagentrunner.py:213-220`); `ENDPOINT_URL` required unless the transport is `in_memory`
  (single-process SSE needs no endpoint: relaxation of `akagentrunner.py:170-172`).
- Permanent-failure hooks mirror `akagentrunner.py:121-130` / `:227-246` (error body / error
  chunk to OUTPUT; self-guarded).
- Entry point: `AgentRunner.run()` classmethod: resolves transport type (`in_memory` → raise, §4),
  dispatches to `StreamAgentRunner` when `execution.mode == STREAM` (as `akagentrunner.py:132-138`),
  builds the `ConsumerLoop` from `queues.input.*` config.

**`ResponseHandler`** (`response_handler.py`): generalized from `ECSOutputConsumer`
(`containerized/akoutputconsumer.py:15`):

- REST modes: write `{"session_id", "request_id", "status_code", "body"}` to the response store
  (`akoutputconsumer.py:144-166` plus the new status field).
- ASYNC/STREAM: push via the configured `WebSocketHandlerABC`: `PodPushWebSocketHandler` on
  k8s/self-hosted, in-process delivery when the transport is `in_memory` (below); message types per
  mode as `akoutputconsumer.py:65-74`.
- STREAM + memory transport: chunks are appended to the `InMemoryResponseStore` stream for the
  request (`add_chunk(request_id, chunk_dict)`) so the SSE generator in the Request Handler can
  drain them: no WS required locally.
- Permanent-failure mirror of `akoutputconsumer.py:85-142` (error entry to store / error frame
  over WS so clients never hang).

**`RequestHandler`** (`request_handler.py`): extends `RestHandler`, which moves into
`pipeline/request_handler.py` (shim left at `deployment/common/rest_handler.py`, which also keeps
an `AKConfig` name so existing patch targets resolve). `RestHandler` enqueues through
`get_transport()` (default: the factory-configured transport) via an internal
`_enqueue_request()` that builds the input-queue envelope (`request_id` attribute,
`group_id=session_id`, `dedup_id=request_id`, body dumped with `exclude_none=True` for byte
parity with the old SQSHandler path); `ECSQueueRequestHandler` inherits this, so ECS enqueues
ride the SQS transport. `RestHandler` stays behavior-identical otherwise, with three overridable
seams (defaults preserve today's ECS behavior exactly):

- `_build_sync_response(record) -> Any` (default: today's `response.get("body", response)`) so
  subclasses can honor `status_code`;
- `_await_response_record(request_id)` (default: today's `get_message_with_retry(...)` call with
  its original keyword style) so subclasses can retrieve full records;
- `_effective_mode()` (default: `execution.mode` as-is) so the pipeline can map unset → REST_SYNC.
- `RestHandler.get_response_store()` defaults to `ResponseStoreFactory.create()` (the factory
  owns the resolution defaults, so ECS and the pipeline share one implementation);
  `RequestHandler._await_response_record` polls **full records** (`ResponseStore.get_record`)
  with the pipeline retry budget, so the stored `status_code` is honored on every store,
  shared backends included.
- `_build_sync_response` override: stored `status_code >= 400` → `HTTPException(status_code,
  detail=body)`: restoring today's **direct-mode** error contract
  (`ResponseBuilder.build_response` raises in `rest_api_mode`, `chat_service.py:299-302`) on the
  pipeline path.
- Routes: `AGENTS_PATH` GET, `CHAT_PATH` POST (enqueue; SSE `StreamingResponse` when
  `mode == STREAM`: drains `InMemoryResponseStore.stream(request_id)`), `CHAT_PATH` GET
  (`rest_async` poll), and `CHAT_MULTIPART_PATH` POST **only when the transport is `in_memory`**:
  uploads are read (bounded by `api.max_file_size`, `config.py:101`) and converted to the
  base64 `images`/`files` fields `RequestBuilder.from_base_request_sync` already consumes
  (`chat_service.py:37,75-117`), then enqueued as ordinary JSON. Broker transports keep today's
  ECS behavior (no multipart route, `rest_handler.py:135-144`).
- `mode=None` is treated as `REST_SYNC` on the pipeline path (parity: both return the same
  success dict `{"result", "session_id"}`; errors raise `HTTPException`: §12 change 1).

**`IOHandler`** (`io_handler.py`): generalized from `ECSIOHandler`
(`containerized/ecs_io_handler.py:10`):

- `IOHandler.run(auth_validator=None)`; topology by transport type:
  - `in_memory` → **single-process**: ThreadRunner tasks = `rest-api` (uvicorn, `graceful=True`,
    `awaited_on_shutdown=False` as `ecs_io_handler.py:50-56`), `response-handler`
    (`ResponseHandler` loop), **and `agent-runner` (`AgentRunner` loop)**: all five components.
  - broker types → **two-process**: `rest-api` + `response-handler` only; `AgentRunner.run()` is
    the second container.
- WS modes (`ASYNC`/`STREAM` over WS): `auth_validator` mandatory (fail-fast as
  `ecs_io_handler.py:32-36`); the REST app additionally mounts `PipelineWebSocketHandler` (§9)
  and the internal push endpoint router.
- **Signal contract**: `IOHandler.run()` serves the app through its own `uvicorn.Server` (via
  the new `RESTAPI.build_app()` seam) and installs SIGTERM/SIGINT handlers on the main thread
  that set `ThreadRunner.shutdown_event`, flag `server.should_exit`, and mark the drain exit
  code 0 (`ThreadRunner.shutdown_exit_code`, default 1 for failure-initiated drains). Required
  because uvicorn installs its own handlers only on the main thread, and a container PID 1 with
  no handler never receives SIGTERM at all (kernel drops default-disposition signals to PID 1;
  found when the pipeline flip hung the `examples/containerized/openai` e2e job). Handler
  installation is skipped off the main thread (tests). The nested `ConsumerLoop`s run with
  `exit_on_shutdown=False`, so each returns after finishing its in-flight work and only
  IOHandler's outer `ThreadRunner.run` exits the process, once every loop has reported in;
  standalone container mains (`AgentRunner.run()`, the ECS classes) keep the exiting default.
  The handler body lives in `ThreadRunner.install_shutdown_signal_handlers` (shared);
  `AgentRunner.run()` installs the same handlers (without the uvicorn step), since a standalone
  runner container in the two-process topology is PID 1 too and must drain on SIGTERM rather
  than hang until SIGKILL. The ECS classes are unchanged.

**`RESTAPI` default wiring** (`api/http.py`): `run()` gains a pipeline delegation guard ahead of
its current body: it lazily imports and delegates to `IOHandler.run()` **only when all three
hold**: `cls is RESTAPI` exactly (subclasses, `AWSRestAPI`, `AWSWebsocketAPI`, keep their own
paths untouched, so ECS never delegates), the caller passed no explicit `handlers`, and
`QueueTransportFactory.resolve_type()` returns `in_memory`. Because `resolve_type()` yields
`in_memory` by default, every existing
`RESTAPI.run()` app boots the single-process pipeline; passing explicit `handlers` (including
`AgentThreadRequestHandler`: Q6: the thread surface stays an inline, IO-side handler in v1)
preserves today's inline path unchanged.

### 9. WebSocket delivery (`ws/`): pod-direct push (design Q3, Option D)

- **`ws/base.py`**: `WebSocketConnectionStoreABC` + `WebSocketHandlerABC` moved verbatim from
  `deployment/common/websocket_service.py:7,65` (shim left behind; AWS subclasses untouched).
- **`LocalConnectionRegistry`** (`ws/registry.py`): implements `WebSocketConnectionStoreABC`
  over two in-process dicts (`user_id → {connection_id: WebSocket}`, `connection_id → user_id`),
  `threading.Lock`-guarded. No TTL (connections die with the pod).
- **`PipelineWebSocketHandler`** (`ws/handler.py`): a **native FastAPI WebSocket route**
  (`/ws`): new code; the ECS handlers assume API-Gateway-proxied HTTP frames with `x-ws-*`
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
  config `websocket_api.push_auth_token` (required whenever the transport is not `in_memory`:
  startup `AKConfigError` otherwise); resolves the user's local connections and writes frames on
  the uvicorn loop via `asyncio.run_coroutine_threadsafe`. Unknown user/no connections → 404
  (the k8s `GoneException` analogue).
- **`PodPushWebSocketHandler`** (`ws/push.py`): implements `WebSocketHandlerABC.send` as the
  HTTP POST above (connection pooling via a module-level `httpx.Client`); 404/connection-refused
  → log + raise so the `ConsumerLoop` retry/permanent-failure semantics apply
  (`max_receive_count` retries, then the error is dropped with a warning: bounded, never
  crash-looping).
- Semantic difference recorded (design R6): replies reach the user's connections on the
  originating pod only.

### 10. Response store changes (`pipeline/response_store/`)

- `ResponseStore` ABC and the Redis/Valkey/DynamoDB stores move (shims at old paths, §1
  rule 3). The selection factory is `ResponseStoreFactory` (`factory.py`, renamed from
  `ResponseDBHandler` with its `Type` enum dropped; #541 shape, `AKConfigError` on unknown
  types): it owns the pipeline resolution defaults in one place (in_memory default on the
  in_memory transport; broker transports require an explicit shared store). The ABC gains
  `get_record` (the full stored record including `status_code`, implemented by every store)
  and an optional chunk-streaming capability (`supports_chunk_streaming` +
  `add_chunk`/`stream`/`close_stream` defaults that fail loudly): pipeline components check
  the capability, never concrete store classes, so BYO stores can take part in SSE delivery.
  `_ResponseStoreConfig.type` (`config.py:314`) accepts a built-in short name
  (`in_memory|redis|valkey|dynamodb`) or a dotted path to a `ResponseStore` subclass (the #541
  BYO branch, `resolve_dotted(type, base=ResponseStore)()`); the old regex pattern is dropped,
  so unknown short names fail loudly at store-build time (`AKConfigError` listing the options)
  rather than at config load, matching the session/thread/trace store factories.
- **Resolution default**: `execution.response_store is None` + transport `in_memory` → in_memory store
  (today's constructor raises `ValueError`, `handler.py:50-51`; the fail-fast behavior is
  preserved for broker transports without a configured store, but the **type changes** to
  `AKConfigError`, which subclasses `Exception` and not `ValueError`, so any caller catching
  `ValueError` must be updated: named in the §12 change 12 changelog note).
- **`InMemoryResponseStore`**: process-wide dict of `request_id → queue.Queue` +
  `threading.Event`-based waiters. `add_message(record)` honors the standard record shape;
  `get_message(request_id, get_and_delete)` returns `record["body"]`: matching the existing
  stores' contract (`response_store/redis.py:28`, `dynamodb.py:25`): but also keeps the full
  record so `RequestHandler._build_sync_response` can read `status_code`; `add_chunk`/`stream`
  support the SSE path (§8). `get_message_with_retry` is inherited unchanged
  (`response_store.py:37-74`).
- **Fail-fast rule** (design R6): at `IOHandler`/`RequestHandler` startup, transport ≠ `in_memory`
  **and** response store type == `in_memory` (or defaulted) in a REST mode → `AKConfigError`
  ("multi-process queue modes need a shared response store").

### 11. Config changes (`core/config.py`)

```python
class _InMemoryQueueConfig(BaseModel):
    ack_wait: float = 300.0    # generous by design: in-process redelivery rescues stuck threads,
                               # and a tight timeout only risks double-running long agent turns
    dedup_window: float = 300.0

class _KafkaQueueConfig(BaseModel):
    bootstrap_servers: str = "localhost:9092"
    input_topic: str = "agent-input"; output_topic: str = "agent-output"
    group_id: str = "agent-kernel"        # consumers append "-input"/"-output"
    dlq_suffix: str = ".dlq"
    retry_backoff: float = 2.0
    delivery_timeout: float = 30.0        # bound on the synchronous send confirm (§6)
    metadata_timeout: float = 5.0         # bound on the startup partition/DLQ capacity check (§6)
    client_config: dict[str, Any] = {}      # passthrough to confluent-kafka (SASL/TLS etc.)

class _NatsQueueConfig(BaseModel):
    url: str = "nats://localhost:4222"
    input_stream: str = "AGENT_REQUESTS"; input_subject_prefix: str = "chat.req"
    output_stream: str = "AGENT_REPLIES"; output_subject_prefix: str = "chat.out"
    partitions: int = 32
    ack_wait: float = 30.0; retry_backoff: float = 2.0
    auto_provision: bool = False

class _QueuesConfig(BaseModel):             # config.py:356: extended
    type: Optional[str] = None              # in_memory|sqs|kafka|nats|<dotted>; None → resolve_type()
    input: _InputQueueConfig = ...          # unchanged (url stays SQS-specific)
    output: _OutputQueueConfig = ...        # unchanged
    batch_size: Optional[int] = ...         # unchanged
    in_memory: Optional[_InMemoryQueueConfig] = None
    kafka: Optional[_KafkaQueueConfig] = None
    nats: Optional[_NatsQueueConfig] = None
```

- `_WebSocketAPIConfig` (`config.py:104-107`) gains `push_auth_token: Optional[str] = None` and
  `push_port: Optional[int] = None` (defaults to `api.port`).
- Field descriptions updated to drop "SQS" where the field is now backend-neutral
  (`_QueuesConfig.input/output` descriptions, `config.py:357-358`); `url` descriptions state
  "SQS only".
- **Compatibility**: existing YAML/`AK_*` env vars are untouched: `type` absent + `url` present
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
   latency is in-process queue hops. **The pipeline additionally introduces bounded-wait
   semantics that the inline path never had** (review finding on #621; defaults chosen to make
   these rare locally):
   - a `rest_sync` request whose agent run exceeds the response wait budget returns 504 while
     the run continues (budget: `response_store.retry_count × delay` when configured; 60 × 1 s
     by default when no `response_store` block exists);
   - the SSE bridge applies the same budget between consecutive chunks and emits an error frame
     on expiry;
   - a run longer than `queues.in_memory.ack_wait` (default 300 s) is redelivered and executed
     again, up to `max_receive_count`, after which a permanent-failure error is delivered even
     though the original run may still complete;
   - stale delivery handles after an `ack_wait` redelivery are inert no-ops (SQS
     receipt-handle parity), so a late ack/nack cannot break per-session FIFO.
   The queue-mode guide's local section carries a prominent caution on tuning both knobs for
   long agent runs.
2. `execution.queues.type` exists; untyped configs resolve exactly as today (`url` ⇒ `sqs`).
3. `/api/v1/chat` GET (`rest_async` poll) becomes available on the local pipeline (was
   ECS-queue-mode-only).
4. `/api/v1/chat-multipart` works in queue mode **on the in_memory transport** (was unavailable in
   any queue mode; still unavailable on broker transports).
5. `mode=None` runs as `REST_SYNC` through the pipeline (same wire shapes as the old inline
   path).
6. Output messages and response-store records now carry `status_code`; the **pipeline** REST
   surface maps stored errors to `HTTPException` (the ECS path keeps returning error bodies with
   HTTP 200: its today's behavior, unchanged). Since the interface cleanup this holds on
   shared stores too: the pipeline polls full records via `ResponseStore.get_record` (§10),
   where it previously saw only bodies outside the in-memory store.
7. `ECSSQSConsumer` internals delegate to `ConsumerLoop`; its public classmethod surface,
   record shapes, log messages, and retry semantics are unchanged.
8. New native `/ws` WebSocket endpoint + `/internal/push` endpoint exist only when `IOHandler`
   runs in a WS mode (ASYNC/STREAM outside AWS API Gateway deployments).
9. The thread surface (`AgentThreadRequestHandler`) stays inline (IO-side) in v1: mounting it
   explicitly bypasses pipeline delegation (§8), so thread recording semantics are unchanged.
10. SIGTERM/SIGINT now shut the single-process pipeline down gracefully with exit code 0:
    consumer loops drain (within the ≤1 s fetch-wait slice plus any in-flight agent run),
    uvicorn stops, the process exits. Pre-pipeline this worked implicitly because uvicorn ran on
    the main thread; the pipeline flip had regressed container stop to a hang on PID-1 runtimes
    with no SIGKILL escalation (the `examples/containerized/openai` harness) and to ungraceful
    SIGKILL-after-grace on orchestrators. Ctrl+C on a local run also now exits cleanly. The
    standalone `AgentRunner.run()` container main installs the same handlers (drain in-flight
    runs, exit 0). SQS consumers drain within one full long-poll interval (≤20 s, §3 rule 5)
    rather than the ≤1 s slice of other transports.
11. Bug fix exposed by the pipeline's thread-based execution:
    `AgentHandler._run_async_sync` (`core/chat_service.py`) previously wrapped
    `run_until_complete(coro)` in `except RuntimeError: asyncio.run(coro)`, so an agent's own
    `RuntimeError` could re-await the consumed coroutine and surface as "cannot reuse already
    awaited coroutine". The fallback now applies only to `get_event_loop()` failing; agent
    exceptions propagate as-is. (The ECS runner shares this code path: strictly an error-fidelity
    improvement.)
12. **Public queue interface cleanup (breaking, decided 2026-08-14)**: the pipeline transport
    (`QueueTransport`/`QueueName`/`QueueMessage` + `QueueTransportFactory`) is the single public
    queue API; configuration resolves the backend and physical queue. Removals, without
    deprecation aliases: the `QueueHandler` ABC (`deployment/common/queue_handler.py`) is
    deleted, with `QueueMessageBody`/`SendMessageAttributes` folded into `SQSHandler` (now
    AWS-internal glue with an unchanged method surface); `QueueConsumer` is renamed
    `RawQueueConsumer` and relocated to `deployment/aws/core/raw_queue_consumer.py`;
    `deployment/common/__init__.py` no longer exports `QueueConsumer`. The `RestHandler`
    enqueue seam is retyped from `get_queue_handler()` to `get_transport()`, so
    `ECSQueueRequestHandler` enqueues through the SQS transport (wire format identical by
    construction; body JSON dumped with `exclude_none=True` as before). Only code importing the
    removed ABCs/paths breaks; `SQSHandler` callers and `ECSSQSConsumer`/`LambdaSQSConsumer`
    subclasses are unaffected. Same wave: `ResponseDBHandler` becomes `ResponseStoreFactory`
    (`response_store/factory.py`, `Type` enum dropped, `AKConfigError` instead of
    `ValueError`, owns the resolution defaults; the `deployment/aws/core/response_store/`
    shim re-exports the new name), `ResponseStore` gains `get_record` + the chunk-streaming
    capability (§10), and the relocated modules' logger names unify under `ak.pipeline.*`
    (`ak.thread_runner` → `ak.pipeline.thread_runner`, `ak.deployment.response_store` and
    `ak.response_db_handler` → `ak.pipeline.response_store`, the WS ABCs →
    `ak.pipeline.ws.*`, RestHandler default → `ak.pipeline.rest_handler`; the ECS classes
    keep their explicit `ak.ecs.*` names). Needs a changelog entry at release.

**Non-changes**: ECS and Lambda wire behavior, entry points, and exports
(`deployment/aws/__init__.py` lazy-export table unchanged); `SQSHandler`'s method surface;
SQS FIFO group/dedup mapping; session/thread/multimodal stores; CLI, A2A, MCP
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
│       │                              #   duplicate_window, max_deliver): nats.enabled
│       └── kafka-cluster.yaml         # Strimzi Kafka/KafkaNodePool/KafkaTopic CRs: kafka.enabled
└── ci/                            # chart-testing config + kind smoke values
```

- **Env-var contract** (the ECS Terraform split preserved: app config declares modes, infra
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
  flags: `promExporter.enabled` for NATS, Strimzi `metricsConfig` + Kafka Exporter for Kafka)
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

- `test_pipeline_in_memory_transport.py`: per-group FIFO under concurrent fetch, ack_wait
  redelivery + receive_count increment, dedup window drop, blocking fetch timeout.
- `test_pipeline_consumer_loop.py`: process/ack ordering, nack-on-raise, permanent-failure
  path (hook then ack), poll-exception 5 s retry, shutdown via `shutdown_event`, async
  `process` dispatch.
- `test_transport_contract.py`: a reusable `QueueTransportContract` (the
  `SandboxProviderContract` pattern, `sandbox/testing.py`) asserting the six queue-semantics
  requirements from `research/current-queue-mode.md`; run against `in_memory` in-repo; `sqs` via
  mocked boto3 (the subclass lives in `test_pipeline_sqs_transport.py`, next to its in-memory
  FIFO fake of the boto3 client); the same class is reused by integration CI against real
  Kafka/NATS containers.
- `test_pipeline_sqs_transport.py`: envelope mapping from boto3 records, send-side kwargs
  equality with `SQSHandler.build_send_message_kwargs` output, long-poll parameters
  (integer `WaitTimeSeconds`, unsliced 20 s wait), factory URL resolution, the SQSHandler
  delegation pins (nested-class identity, shared kwargs builder, duplicate-attribute rejection),
  plus the contract suite over the mocked-boto3 FIFO fake.
- `test_pipeline_kafka_transport.py`: a fake in-memory cluster (per-partition logs, fetch
  positions independent of committed offsets, delivery callbacks) behind
  `confluent_kafka.Consumer/Producer`: envelope/header/key mapping, synchronous send confirm
  (delivery error and unconfirmed-delivery both raise), commit-after-ack, nack requeue without
  commit, DLQ produce plus commit-on-DLQ-failure, partition-EOF skip vs fatal record error,
  client/producer config (manual commit, cooperative-sticky, `max.poll.interval.ms`, per-queue
  group ids, `client_config` passthrough, producer sharing), the head-of-line-blocking tradeoff
  with a forced partition collision, factory resolution, plus the full `QueueTransportContract`
  (with `timeout_redelivery = False`).
- `test_pipeline_bookkeeping.py`: one shared assertion set run against both bookkeeping backends
  (attempt counts, retry-safe dedup claims incl. owner reclaim, expiry), key prefixes and
  create-only counter TTL on the driver-backed store, and factory selection from the session
  config incl. the once-per-process fallback warning.
- `test_pipeline_nats_transport.py`: faked `nats` client on a real `_NatsLoop`: subject
  construction, `Nats-Msg-Id`, `num_delivered` mapping, `term()` on permanent failure,
  `auto_provision=false` verification error.
- `test_pipeline_agent_runner.py` / `test_pipeline_response_handler.py`: mirror the assertions
  of `test_akagentrunner_stream.py`/`test_akresponsehandler.py` on the generalized classes,
  including `STATUS_CODE` propagation and the in_memory-STREAM chunk path.
- `test_pipeline_request_handler.py`: FastAPI `TestClient` over the single-process pipeline:
  `rest_sync` parity (success dict + HTTPException on stored error), `rest_async`
  accept/poll, SSE streaming end-to-end, multipart-on-in_memory, multipart-absent on broker
  transports (mocked).
- `test_pipeline_ws.py`: native `/ws` route (auth, registry lifecycle), `/internal/push`
  (token auth, 404 on unknown user, frame delivery), `PodPushWebSocketHandler` retry-on-404.
- `test_response_store_in_memory.py`: record shape (`get_message` returns `body`), status_code
  retention, chunk streaming, `get_message_with_retry` inheritance, `ResponseStoreFactory`
  selection (in_memory default on the in_memory transport, broker fail-fast, BYO dotted path,
  wrong base and unknown short name fail loudly), and the chunk-streaming capability defaults.
  `test_response_store_valkey.py` additionally covers `get_record` round trips.

Existing tests: the riskiest consumer is `ECSSQSConsumer` (its internals move):
`test_ecs_sqs_consumer_parallel.py` must pass **unmodified**: it imports and patches the class
surface directly (`tests/test_ecs_sqs_consumer_parallel.py:5`, classmethod seams `poll`,
`process_message`, `delete_message`, `_get_client`), which the shim preserves.

**Pass unmodified**: `test_ecs_sqs_consumer_parallel.py`, `test_akagentrunner_stream.py`,
`test_akresponsehandler.py`, `test_thread_runner.py` (import path via the `deployment/common`
shim).

**Sanctioned edits**, each forced by a numbered behavioural change and expected to appear in the
diff:

- `test_api_http.py`: gains a delegation test class (delegates when unconfigured + in_memory;
  never for explicit handlers, subclasses, or broker transports), and its two pre-existing
  bare-`RESTAPI.run()` tests pin a broker transport via `QueueTransportFactory.resolve_type`
  (change 1: the bare-run default now genuinely boots the pipeline).
- `test_sqs_handler.py`: drops the assertion that `QueueMessageBody`/`SendMessageAttributes` are
  inherited from the deleted `QueueHandler` ABC; the models are now `SQSHandler`'s own and every
  other assertion in the file is untouched (change 12).
- `test_rest_handler_poll.py`: its fake handler implements `get_transport()` instead of
  `get_queue_handler()` (change 12's seam retype).
- `test_config.py`: the `_ResponseStoreConfig` pattern-rejection test becomes a dotted-path
  acceptance test, with the fail-loud case moving to `test_response_store_in_memory.py`
  (change 12: the type field accepts BYO paths and validates at build time).
- `test_pipeline_consumer_loop.py`: the "not available yet" factory case switches from `kafka` to
  `nats` as each built-in transport lands.
- `test_response_store_valkey.py`: `ResponseDBHandler` references become `ResponseStoreFactory`,
  and the missing-block case expects `AKConfigError` rather than `ValueError` (change 12).

Run: `cd ak-py && uv run pytest`. Chart CI: `ct lint` + kind install smoke per flavor values
file with one end-to-end chat request through the NATS transport.
