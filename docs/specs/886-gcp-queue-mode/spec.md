# #886: Queue mode on GCP — Implementation Spec

This spec details how the approved [design](design.md) is built. It adds a built-in `pubsub` queue
transport, teaches the delivery bookkeeping to use a Redis response store, makes `CloudRun.run()`
start the pipeline, and adds the Terraform for a second Cloud Run tier. The design idea is
unchanged: reuse `IOHandler`, `AgentRunner`, `ConsumerLoop`, the Redis response store and Kafka's
bookkeeping, and add only what GCP lacks. External facts are in
[research/pubsub-cloud-run.md](research/pubsub-cloud-run.md) (cited as "research §N").

Code references are at `develop` @ `25cce1e4`. The Pub/Sub client facts were read from
`google-cloud-pubsub` 2.43.0.

**Design amendments** found while detailing are listed in [§7](#7-design-amendments-for-re-review).
They need re-review before implementation starts.

## Design

### 1. Pub/Sub transport (`pipeline/transport/pubsub.py`)

#### 1.1 Layout

```
pipeline/transport/
├── base.py         # + "pubsub" factory branch, + "pubsub" in _BUILTIN_TYPES
├── bookkeeping.py  # + acked-message memory, + response-store resolution step
└── pubsub.py       # new: PubSubEnvelopeCodec, _LeaseKeeper, PubSubTransportConsumer, PubSubTransport
```

`pubsub.py` imports `google.cloud.pubsub_v1` and `google.api_core.exceptions` at module scope,
like `kafka.py` imports `confluent_kafka` (`pipeline/transport/kafka.py:35`). The factory imports
it inside `require_extra("pubsub", ...)`, so nothing else loads the SDK.

#### 1.2 Classes

| Class | Responsibility |
|---|---|
| `PubSubEnvelopeCodec` | Encodes a `QueueMessage` to Pub/Sub `data` + attributes, and back. Stateless; static methods |
| `_LeaseKeeper` | One daemon thread per consumer. Extends the ack deadline of every leased message until `ack_wait` |
| `PubSubTransportConsumer(TransportConsumer)` | One per consumer thread. Pull, hold, serve one message per ordering key, ack/nack/dead-letter |
| `PubSubTransport(QueueTransport)` | Process-wide send side, consumer factory, provisioning (create or verify) |

```python
class PubSubEnvelopeCodec:
    ENVELOPE_ATTRIBUTE = "ak-envelope"   # the only Pub/Sub attribute Agent Kernel sets
    ENVELOPE_VERSION = "1"

    @staticmethod
    def encode(message: QueueMessage) -> tuple[bytes, dict[str, str]]: ...  # (data, attributes)

    @staticmethod
    def decode(data: bytes, attributes: Mapping[str, str], ordering_key: str, message_id: str) -> QueueMessage: ...
        # raises ValueError when the marker is missing or the data is not the envelope


class _LeaseKeeper:
    def __init__(self, subscriber, subscription: str, ack_wait: float, request_timeout: float,
                 clock: Callable[[], float] = time.monotonic): ...
    def add(self, ack_ids: list[str]) -> None: ...      # records fetched_at = clock()
    def remove(self, ack_ids: list[str]) -> None: ...
    def tick(self) -> None: ...                         # one renewal pass; the thread calls it every LEASE_REFRESH_SECONDS
    def stop(self) -> None: ...


class PubSubTransportConsumer(TransportConsumer):
    def __init__(self, subscriber, subscription: str, dlq_topic: str, publisher,
                 bookkeeping: BookkeepingStore, ack_wait: float, request_timeout: float): ...
    def fetch(self, batch_size: int, wait_seconds: float) -> list[QueueMessage]: ...
    def ack(self, message: QueueMessage) -> None: ...
    def nack(self, message: QueueMessage) -> None: ...
    def dead_letter(self, message: QueueMessage) -> None: ...
    def close(self) -> None: ...


class PubSubTransport(QueueTransport):
    def __init__(self, project_id: str | None, input_topic: str, input_subscription: str,
                 output_topic: str, output_subscription: str, dlq_suffix: str = "-dlq",
                 ack_wait: float = 300.0, request_timeout: float = 10.0, auto_provision: bool = False,
                 max_delivery_attempts: dict[QueueName, int] | None = None,
                 bookkeeping: BookkeepingStore | None = None, config_path: str = "execution.queues",
                 feature: str = "execution.queues.type: pubsub"): ...
    def send(self, queue: QueueName, message: QueueMessage) -> Any: ...   # {"MessageId": <pubsub id>}
    def create_consumer(self, queue: QueueName) -> PubSubTransportConsumer: ...
    @classmethod
    def reset(cls) -> None: ...                                            # test isolation only
```

Module constants (each with a one-line comment in code):

| Constant | Value | Why |
|---|---|---|
| `LEASE_EXTENSION_SECONDS` | `60` | Deadline set per renewal. Six times the refresh interval, so five missed renewals still keep the lease |
| `LEASE_REFRESH_SECONDS` | `10` | How often `_LeaseKeeper` renews |
| `SUBSCRIPTION_ACK_DEADLINE_SECONDS` | `10` | The subscription's own deadline (Pub/Sub's minimum, research §4). It only covers the moment between a pull response and the first renewal, and a message lost to a cancelled pull ([§1.5](#15-receive-side)) |
| `DEFAULT_MAX_DELIVERY_ATTEMPTS` | `5` | Pub/Sub's own default, used by `auto_provision` when the factory gives none |
| `MIN_PULL_TIMEOUT_SECONDS` | `0.05` | Floor on a pull's client deadline: a zero gRPC deadline fails before it is sent |
| `ERROR_ATTRIBUTE` | `"ak-error"` | Added to a dead-letter copy (Kafka's `ERROR_HEADER`, `kafka.py:46`) |

Module-level functions: none. Every helper is a method of the class that uses it.

#### 1.3 Rules

1. **The transport never reads `AKConfig`.** The factory passes every value (architecture rule 4).
   The one exception is `BookkeepingStoreFactory.create()` when no store is injected, which Kafka
   already does (`kafka.py:324`).
2. **Pull only, unary.** `SubscriberClient.pull(request={"subscription", "max_messages"},
   timeout=wait, retry=None)`. No streaming pull, no push (design Non-goals).
3. **One ordering key in flight per consumer, one batch outstanding per key on the server.**
   Pub/Sub sends a key's next batch only after the outstanding one is acked or has lapsed
   (research §1). The consumer serves that batch one message at a time.
4. **`receive_count` comes from the bookkeeping store**, never from `delivery_attempt`
   (approximate, can reset, research §2).
5. **Bookkeeping keys are scoped to the full subscription path**, like Kafka scopes dedup to the
   topic (`kafka.py:247-257`). A reply carries its request's `dedup_id` (`agent_runner.py:291`), so
   a global key would drop every reply.
6. **`ack` never raises.** Processing has already succeeded, so a failure is logged, and the
   acked-message memory drops any redelivery (Kafka parity, `kafka.py:101-116`).

#### 1.4 Wire format (`PubSubEnvelopeCodec`)

- `data` is the UTF-8 JSON object `{"body": <str>, "attributes": {<str>: <str>}, "dedup_id": <str|null>}`.
- Pub/Sub `attributes` hold only `{"ak-envelope": "1"}`.
- `group_id` travels as the Pub/Sub `ordering_key` (`""` when `None`), and decodes back to `None` when empty.
- `message_id` is Pub/Sub's own `message_id`. `receive_count` is set by the consumer, not the codec.
- Why the whole envelope goes in `data`:
  - Pub/Sub caps attributes at 100 per message and 1024 bytes per value (research §8). The
    `reply_` context alone may be 8192 bytes (`integration/adapter/producer.py:22`).
  - `data` holds up to 10 MB, so attributes round-trip byte for byte with no spill-over scheme.
  - The marker lets a future encoding change be detected, and lets an operator filter Agent Kernel
    traffic.
- `decode` raises `ValueError` for a message without the marker or with malformed data. The
  consumer quarantines it ([§1.5](#15-receive-side)).

#### 1.5 Receive side (`PubSubTransportConsumer`)

State, all owned by the consumer thread except the lease registry:

- `_held: dict[str, deque[_Received]]`: pulled but not yet served, per ordering key. Keyless
  messages sit under `""` and are not ordered.
- `_in_flight: dict[str, _Received]`: the one served, unsettled message per non-empty key.
- `_Received` is a frozen dataclass: `ack_id`, `message_id`, `ordering_key`, `envelope`
  (a `QueueMessage`, or `None` when decoding failed), `raw` (the Pub/Sub message, for the
  dead-letter copy).

`fetch(batch_size, wait_seconds)`:

1. Serve from `_held` (step 4). If that yields anything, return it without pulling.
2. Otherwise pull `max(batch_size, 1)` messages with `timeout=wait_seconds` and `retry=None`.
   `DeadlineExceeded` means an empty wait and returns `[]`. Any other `GoogleAPICallError`
   propagates, and `ConsumerLoop` backs off (`consumer.py:115-120`).
3. For each pulled message:
   - Lease it: one batched `modify_ack_deadline(ack_ids, ceil(min(LEASE_EXTENSION_SECONDS,
     ack_wait)))`, then `_LeaseKeeper.add`. The first renewal is immediate so `ack_wait` holds even
     when it is below the subscription's deadline.
   - A pulled message for key K **supersedes** local state for K: Pub/Sub resends K only after
     the previous batch was acked or lapsed (rule 3), so `_in_flight[K]` and `_held[K]` are stale.
     They are dropped and their leases removed, without a server call.
   - Append to `_held[K]` in pull order.
4. Serve: walk `_held`. For each key without an in-flight message (keyless always qualifies),
   pop the head and check it in this order:
   1. Undecodable → quarantine: publish the raw copy to the dead-letter topic with `ak-error`, ack,
      log at ERROR. Continue.
   2. `bookkeeping.was_acked(<sub>:<message_id>)` → a cascade or lost-ack redelivery (research §1):
      ack without running, log at INFO. Continue.
   3. `bookkeeping.claim_dedup(<sub>:<dedup_id>, owner=<message_id>)` is False → a publish-side
      duplicate: ack, log at INFO (Kafka's wording, `kafka.py:239`). Continue.
   4. `receive_count = bookkeeping.incr_attempts(<sub>:<message_id>)`; record in `_in_flight`;
      add to the batch. Stop at `batch_size`.
   - At most one message per non-empty key per batch. Keyless messages fill the rest.

`ack(message)`:

- `mark_acked(<sub>:<message_id>)`, then `acknowledge([ack_id])` with `timeout=request_timeout`.
  The mark goes first: if the ack call is lost, the redelivery is dropped by step 4.2.
- Always, in `finally`: remove the lease, clear `_in_flight[K]`, `clear_attempts`.
- Each call is wrapped; a failure is logged with `_log.exception` and never raised (rule 6).

`nack(message)`:

- Collect the message plus every `_held[K]` entry for its key, and drop them locally (lease,
  in-flight, held) **before** the server call, so local state is clean whatever happens.
- One `modify_ack_deadline(ack_ids, 0)`. The subscription's retry policy sets the delay. Pub/Sub
  then redelivers the key's messages in order (research §1).
- The held messages are released too: serving them after a nacked predecessor would break order.
- An RPC failure propagates to `ConsumerLoop._safe_nack`, which logs it (`consumer.py:155-160`).
  The lease is already gone, so the message comes back when its deadline passes.

`dead_letter(message)`:

- Publish the message's original `data` and attributes, plus `ak-error: exceeded max_receive_count
  after N deliveries`, to `<topic><dlq_suffix>` with no ordering key. Wait `request_timeout`.
- On any failure, log at ERROR that the copy is lost. Then `ack(message)` either way (Kafka parity,
  `kafka.py:133-148`): the permanent-failure hook has already answered the caller.

`close()`:

- Stop `_LeaseKeeper`. Release every held and in-flight message with one
  `modify_ack_deadline(..., 0)`, so another consumer gets them now rather than after the lease.
- `subscriber.close()`. Failures are logged at DEBUG and swallowed, as NATS does (`nats.py:167-174`).

`fetch_wait_slice_seconds` stays `None` (the loop's 1 s slice), so drains stay prompt.

**Known cost of unary pull with short client deadlines.** `ConsumerLoop` slices waits to ~1 s
(`consumer.py:104-112`), so an idle consumer cancels one pull per second. A message the server
assigns to a pull just as it is cancelled is lost in transit and redelivered when the subscription
deadline passes. That is why `SUBSCRIPTION_ACK_DEADLINE_SECONDS` is the 10 s minimum: the worst case
is a 10 s stall for that one message (and its key). It is not a correctness issue. The live run
measures it ([Testing](#testing)); see [§7](#7-design-amendments-for-re-review) item 3.

#### 1.6 Leases (`_LeaseKeeper`)

- A daemon thread named `pubsub-lease-<subscription short name>`, started in the consumer's
  `__init__` and stopped by `close()`.
- Registry `{ack_id: fetched_at}` behind a `threading.Lock`: the consumer thread adds and removes,
  the keeper thread reads. This is the only state shared between two threads in the transport.
- `tick()`, every `LEASE_REFRESH_SECONDS` via `threading.Event.wait`:
  - for each ack id, `remaining = ack_wait - (clock() - fetched_at)`;
  - `remaining <= 0` → drop it from the registry. The lease lapses and Pub/Sub redelivers, so a turn
    longer than `ack_wait` runs again, as on NATS (design);
  - otherwise renew with `ceil(min(LEASE_EXTENSION_SECONDS, remaining))`, one
    `modify_ack_deadline` call per distinct deadline value.
- A failed renewal is logged at WARNING and retried on the next tick. The lease has
  `LEASE_EXTENSION_SECONDS` of headroom.
- Held messages are leased too (design). They were fetched with the in-flight one, so they lapse
  together.

#### 1.7 Send side (`PubSubTransport.send`)

- `_ensure_topic(queue)` first ([§1.8](#18-provisioning)).
- `publisher.publish(topic_path, data, ordering_key=group_id or "", **attributes)`, then
  `future.result(timeout=request_timeout)`. A timeout or error raises to the caller, which surfaces
  as a failed request, never a silent drop (Kafka parity, `kafka.py:326-361`).
- On any failure for a non-empty key, call `publisher.resume_publish(topic_path, key)` before
  re-raising. With ordering enabled, the client pauses a key after a failed publish and refuses
  every later publish for it (`PublishToPausedOrderingKeyException`) until resumed.
- The publisher is process-wide (class-level, built under a lock), like Kafka's producers
  (`kafka.py:293-294`):
  - `PublisherOptions(enable_message_ordering=True)`;
  - `BatchSettings(max_messages=1)`: `send` waits for every publish, so batching would only add its
    10 ms `max_latency` to each send.
- `PUBSUB_EMULATOR_HOST` is honored by the client itself (`publisher/client.py:133`,
  `subscriber/client.py:85` in 2.43.0), so the transport has no emulator code.
- The project is `project_id`, else the project of `google.auth.default()`, resolved once per
  process and cached on the class. Neither → `AKConfigError` naming `<config_path>.pubsub.project_id`.

#### 1.8 Provisioning

Follows the NATS rule (`nats.py:330-415`): create or verify once per process per object, recorded
only after success, one lock per object.

- **Send side** verifies or creates the queue topic on first `send`.
- **Receive side** verifies or creates, in `create_consumer`: the subscription and its dead-letter
  topic. It never publishes to the queue topic, so it does not check it (and needs no rights on it).
- **Verify** (`auto_provision: false`, the default):
  - `get_topic` / `get_subscription` with `timeout=request_timeout`. `NotFound` → `AKConfigError`
    naming the object and both fixes: the `ak-gcp` `pubsub` module, or `auto_provision: true`.
  - A subscription without `enable_message_ordering` → `AKConfigError`. Ordering cannot be changed
    after creation, so the error says to recreate it.
  - A missing dead-letter topic is an `AKConfigError` too, not Kafka's warning
    (`kafka.py:391-398`): `dead_letter` publishes to it, and Terraform always creates it.
  - IAM: this needs `pubsub.topics.get` and `pubsub.subscriptions.get`, so Terraform grants
    `roles/pubsub.viewer` on exactly these resources ([§5](#5-terraform)).
- **Create** (`auto_provision: true`, emulator and dev only):
  - the queue topic and `<topic><dlq_suffix>`;
  - the subscription: `enable_message_ordering=True`,
    `ack_deadline_seconds=SUBSCRIPTION_ACK_DEADLINE_SECONDS`, and a dead-letter policy with
    `max_delivery_attempts` from the factory;
  - a subscription on the dead-letter topic named like the topic, because Pub/Sub discards messages
    published to a topic with no subscription;
  - `AlreadyExists` is success; no retry policy is set (Pub/Sub's immediate default).
- `check_consumer_capacity` keeps the base no-op (`transport/base.py:30-39`).

### 2. Delivery bookkeeping (`pipeline/transport/bookkeeping.py`)

#### 2.1 Resolution order

`BookkeepingStoreFactory.create(feature=...)`:

1. `session.type` `redis` or `valkey` with its block set: unchanged (`bookkeeping.py:135-148`).
2. **New:** `execution.response_store.type` `redis` or `valkey` with its block set: the same
   `_redis_like` build over `response_store.redis.url` / `.valkey.url`.
3. The process-local fallback with its one-time warning. The warning text gains the new option:
   "Configure session.type or execution.response_store.type redis or valkey...".

- `execution` is read with `getattr(config, "execution", None)` and `response_store` may be `None`
  (`core/config.py:719-722`).
- The key prefixes stay the bookkeeping ones (`ak:qattempts:`, `ak:qdedup:`, new `ak:qacked:`),
  never the response store's `ak:responses:` prefix, so the two cannot collide in one Redis.
- The order applies to every caller (Kafka and Pub/Sub). Session first keeps today's Kafka
  deployments on the store they use now.

#### 2.2 Acked-message memory

Two new abstract methods on `BookkeepingStore`:

```python
@abstractmethod
def mark_acked(self, key: str) -> None:
    """Remember that ``key``'s record was acknowledged, for the dedup window."""

@abstractmethod
def was_acked(self, key: str) -> bool:
    """Whether ``key``'s record was acknowledged within the dedup window."""
```

- `InMemoryBookkeepingStore`: a `{key: expiry}` dict under the existing lock, expired on access,
  TTL = its `dedup_ttl`.
- `RedisLikeBookkeepingStore.__init__(attempts_driver, dedup_driver, acked_driver=None)`:
  - `acked_driver=None` falls back to `dedup_driver` with keys prefixed `acked:`, so existing
    two-argument constructions (the tests at `tests/test_pipeline_bookkeeping.py:113-116`) still work;
  - the factory always passes a third driver: prefix `ak:qacked:`, TTL `DEFAULT_DEDUP_TTL_SECONDS`;
  - `mark_acked` is `set(key, "1")`; `was_acked` is `get(key) is not None`.
- Why the dedup TTL (300 s) is long enough: a cascade arrives at most `LEASE_EXTENSION_SECONDS`
  (60 s) plus the retry policy's maximum backoff (60 s, [§5](#5-terraform)) after the ack it
  repeats.
- Kafka never calls the new methods. Both stores are internal (no factory BYO branch), so the new
  abstract methods break no user code.

### 3. Configuration (`core/config.py`)

Reused whole and unchanged: `_QueuesConfig.input`/`output` (`max_receive_count`,
`no_of_consumers`), `_QueuesConfig.batch_size`, `_ResponseStoreConfig` with its `redis` block, and
`session`.

New model, placed after `_NatsQueueConfig` (`core/config.py:588`):

```python
class _PubSubQueueConfig(BaseModel):
    project_id: str | None = Field(default=None, description="GCP project that owns the topics and subscriptions. Unset uses the project of Application Default Credentials")
    input_topic: str = Field(default="agent-input", description="Topic carrying chat requests")
    input_subscription: str = Field(default="agent-input", description="Subscription the agent runner pulls chat requests from. Must have message ordering enabled")
    output_topic: str = Field(default="agent-output", description="Topic carrying agent replies")
    output_subscription: str = Field(default="agent-output", description="Subscription the response handler pulls replies from. Must have message ordering enabled")
    dlq_suffix: str = Field(default="-dlq", description="Suffix appended to a topic name for its dead-letter topic, where permanently failed messages are copied")
    ack_wait: float = Field(default=300.0, description="Seconds a fetched message stays leased before Pub/Sub redelivers it. Must exceed your longest agent turn: a turn that outlives it is redelivered and executed a second time")
    request_timeout: float = Field(default=10.0, description="Seconds to wait for a Pub/Sub call (publish, ack, admin) to complete")
    auto_provision: bool = Field(default=False, description="Create the topics, dead-letter topics and subscriptions at startup if missing. For the emulator and dev only; leave false in production, where Terraform owns them and a missing object should fail loudly")
```

- `_QueuesConfig` gains `pubsub: _PubSubQueueConfig | None = Field(default=None, description="pubsub transport settings")`,
  and its `type` description becomes `in_memory | sqs | kafka | nats | pubsub` (`core/config.py:628-636`).
- Every field's reason it cannot be derived is in the design's table. No retry-backoff field:
  the subscription's retry policy owns the redelivery delay (design, `nack`).
- The emulator needs no field: the client reads `PUBSUB_EMULATOR_HOST` itself.
- Env: `AK_EXECUTION__QUEUES__PUBSUB__<FIELD>` through the existing `AK_` nesting.

### 4. Factory (`pipeline/transport/base.py`)

- `_BUILTIN_TYPES = ("in_memory", "sqs", "kafka", "nats", "pubsub")` (`base.py:103`), and the class
  docstring's "All four built-ins" becomes five.
- A `pubsub` branch after `nats` (`base.py:167-194`), the same shape:

```python
if transport_type == "pubsub":
    with require_extra("pubsub", f"{config_path}.type: pubsub"):
        from .pubsub import PubSubTransport

    pubsub_config = getattr(queues, "pubsub", None) if queues is not None else None
    if pubsub_config is None:
        raise AKConfigError(f"the pubsub transport requires a {config_path}.pubsub configuration block")
    return PubSubTransport(
        project_id=pubsub_config.project_id, ...,  # every _PubSubQueueConfig field
        # The server's dead-letter backstop sits one delivery past the loop's limit, inside Pub/Sub's 5-100 range.
        max_delivery_attempts={queue: min(max(cfg.max_receive_count + 1, 5), 100)
                               for queue, cfg in ((QueueName.INPUT, queues.input), (QueueName.OUTPUT, queues.output))},
        config_path=config_path,
        feature=f"{config_path}.type: pubsub",  # quoted by BookkeepingStoreFactory's missing-extra error
    )
```

- `PubSubTransport.__init__` therefore also takes `feature: str`, forwarded to
  `BookkeepingStoreFactory.create(feature=...)` when no store is injected. The store is built on
  the first `create_consumer`, not in `__init__`: the send side never needs one.
- The sandbox broker's `queues_config` seam needs no change: an explicit block flows through the
  same branch (`base.py:122-131`).
- `pyproject.toml`: a new `pubsub = ["google-cloud-pubsub>=2.43.0"]` extra next to `kafka` and
  `nats` (`ak-py/pyproject.toml:94-100`). `ak-py/build.sh:13` installs all extras for tests, so CI
  picks it up once `uv.lock` is refreshed.

### 5. Terraform

Facts below are from `ak-deployment/ak-gcp` at `25cce1e4`. "Both roots" means `serverless/` and
`containerized/`, which are the same shape: `serverless/cloud_function.tf:91-187` and
`containerized/cloud_run.tf:85-188` each define one `google_cloud_run_v2_service.service`.

#### 5.1 Layout

```
ak-gcp/common/modules/
├── pubsub/          # new: topics, dead-letter topics, subscriptions, Pub/Sub service-agent IAM
└── agent-runner/    # new: runner service account + IAM, google_cloud_run_v2_worker_pool, optional CREMA
ak-gcp/{serverless,containerized}/
├── queue_mode.tf    # new: module "pubsub", module "agent_runner", runner image build, edge IAM, queue env
├── variables.tf     # + queue_mode, execution_mode, message_type, queue_config, agent_runner, scaling_config
├── state.tf         # session/thread env extracted to a local; gateway default map gains queue-mode routes
├── cloud_run.tf / cloud_function.tf  # + queue env, + cpu_idle in queue mode
├── api_gateway.tf   # path builder groups methods by path
└── main.tf          # provider floor >= 6.37.0
```

- The modules live in `common/` so both roots share one copy. AWS instead keeps `queues` and
  `agent-runner` inside each root (`ak-aws/containerized/queue_mode.tf:8,25`); GCP's two roots
  are close enough to share.
- The roots reference `yaalalabs/ak-common/google//modules/<name>` **without** a `version`
  (e.g. `containerized/state.tf:105,117,136,151`), so a released root resolves the latest
  `ak-common`. The new submodules must therefore ship in an `ak-common` release before roots that
  use them; `sync-terraform.yaml:46-57` releases all three together, and CI rewrites the sources to
  local paths (`scripts/deploy/inject_dependencies.py:25-32`). No workflow change.

#### 5.2 Module `pubsub`

Inputs: `project_id`, `prefix`, `input_queue_max_receive_count`, `output_queue_max_receive_count`,
`dlq_suffix` (default `"-dlq"`), `labels`.

| Resource | Settings |
|---|---|
| `google_pubsub_topic` × 4 | `${prefix}-agent-input`, `${prefix}-agent-output`, and each name + `dlq_suffix` |
| `google_pubsub_subscription` input, output | Same name as its topic. `enable_message_ordering = true`; `ack_deadline_seconds = 10` (the transport's `SUBSCRIPTION_ACK_DEADLINE_SECONDS`); `dead_letter_policy { dead_letter_topic = <dlq topic>, max_delivery_attempts = min(max(n, 5), 100) }`; `retry_policy { minimum_backoff = "2s", maximum_backoff = "60s" }`; `expiration_policy { ttl = "" }` |
| `google_pubsub_subscription` on each dead-letter topic | Same name as the dead-letter topic; `expiration_policy { ttl = "" }`. Pub/Sub drops messages published to a topic with no subscription |
| `google_pubsub_topic_iam_member` | Pub/Sub service agent `service-<project number>@gcp-sa-pubsub.iam.gserviceaccount.com` gets `roles/pubsub.publisher` on both dead-letter topics |
| `google_pubsub_subscription_iam_member` | The same agent gets `roles/pubsub.subscriber` on both main subscriptions (required for dead-letter forwarding) |

- `expiration_policy { ttl = "" }`: by default Pub/Sub deletes a subscription after 31 days without
  activity. A quiet deployment must not lose its queues.
- `retry_policy`: the 2 s minimum matches Kafka's and NATS's `retry_backoff` default
  (`core/config.py:576,610`). The 60 s maximum bounds how late a cascade can arrive
  ([§2.2](#22-acked-message-memory)).
- **`max_receive_count` semantics follow AWS:** the user value `n` counts deliveries. The app gets
  `max(1, n - 1)`, so its permanent-failure hook runs on delivery `n`; Pub/Sub's backstop is `n`,
  one past the loop's limit (design), clamped to Pub/Sub's 5–100 range (research §2). This is
  exactly AWS's split (`ak-aws/containerized/modules/agent-runner/main.tf:11`).
- Outputs: the four names, `dlq_suffix`, and the topic and subscription ids for IAM.

#### 5.3 Module `agent-runner`

Inputs: `project_id`, `region`, `prefix`, `image_url`, `command`, `args`, `cpu`, `memory`,
`instance_count`, `environment_variables` (map), `vpc_connector_id`, the `pubsub` module's outputs,
`grant_firestore` (bool), `scaling` (the `scaling_config` object), `labels`.

- **Service account** `${substr(prefix, 0, 26)}-rnr`, with `roles/logging.logWriter`, and
  `roles/datastore.user` when `grant_firestore` (the edge's grants, `cloud_run.tf:9-21`).
- **Pub/Sub IAM** on named resources only:
  - `roles/pubsub.subscriber` and `roles/pubsub.viewer` on the input subscription;
  - `roles/pubsub.publisher` and `roles/pubsub.viewer` on the output topic;
  - `roles/pubsub.publisher` and `roles/pubsub.viewer` on the input dead-letter topic.
  - `viewer` is for the transport's verify calls ([§1.8](#18-provisioning)).
- **`google_cloud_run_v2_worker_pool.runner`** (GA since provider 6.37.0, research §11):
  - `name = "${prefix}-runner"`, `launch_stage = "GA"`, `deletion_protection = false` (its default
    is `true`, unlike the services');
  - `scaling { manual_instance_count = instance_count }`, and
    `lifecycle { ignore_changes = [scaling[0].manual_instance_count] }` because CREMA changes it.
    AWS does the same with `desired_count` (`ak-aws/containerized/modules/agent-runner/main.tf:387`). Consequence,
    as on AWS: after creation, `instance_count` changes need a manual update or CREMA;
  - `template.vpc_access { connector = vpc_connector_id, egress = "PRIVATE_RANGES_ONLY" }`: the
    root's existing connector, so it reaches Memorystore the way the edge does
    (`cloud_run.tf:106-109`). The worker-pool schema has `vpc_access.connector`, and
    `gcloud run worker-pools deploy` has `--vpc-connector`. Direct VPC egress is not used: with a
    user-supplied `network_id`, `private_subnet_id` may be null (`variables.tf:133-137`);
  - one container: `image = image_url`, `command`, `args`,
    `resources { limits = { cpu, memory } }`, `env` from `environment_variables`. No ports and no
    probes: a worker pool has no endpoint.
- **CREMA** (when `scaling.enabled`), from the Pub/Sub tutorial
  (`docs.cloud.google.com/run/docs/tutorials/autoscale-workerpools-pubsub`):
  - its own service account with `roles/parametermanager.parameterViewer`,
    `roles/monitoring.viewer` and `roles/monitoring.metricWriter` on the project;
    `roles/run.developer` on the worker pool (`google_cloud_run_v2_worker_pool_iam_member`);
    `roles/iam.serviceAccountUser` on the runner's service account only (the tutorial grants it
    project-wide); `roles/pubsub.viewer` on the input subscription;
  - `google_parameter_manager_parameter` (`format = "YAML"`, global) and a
    `google_parameter_manager_parameter_version` whose `parameter_data` is a `yamlencode`d
    `CremaConfig`: `pollingInterval: 30`, a `podIdentity`/`gcp` trigger authentication, one scaled
    object targeting `projects/<p>/locations/<r>/workerpools/<name>` with a `gcp-pubsub` trigger
    (`subscriptionName`, `mode: SubscriptionSize`, `value: <backlog_target>`), and
    `minReplicaCount`/`maxReplicaCount` from `scaling`;
  - a `google_cloud_run_v2_service` running
    `us-central1-docker.pkg.dev/cloud-run-oss-images/crema-v1/autoscaler:1.0` with
    `CREMA_CONFIG = <parameter version name>`, `OUTPUT_SCALER_METRICS = "True"`,
    `resources { cpu_idle = false }`, `scaling { min_instance_count = 1 }`, and no invoker binding.
  - **To confirm at implementation:** the tutorial's config has no `minReplicaCount`/
    `maxReplicaCount`. They are KEDA `ScaledObject` fields; if CREMA ignores them, `min_count` and
    `max_count` are dropped from `scaling_config` and the design's scaling point is amended.
- Outputs: `worker_pool_name`, `service_account_email`.

#### 5.4 Root variables (both roots)

| Variable | Type / default | Validation |
|---|---|---|
| `queue_mode` | `bool`, `false` | `!var.queue_mode \|\| var.create_redis_cluster`: "queue mode needs Memorystore for the response store" |
| `execution_mode` | `string`, `"rest_sync"` | One of `rest_sync`, `rest_async`: `async` and `realtime` are non-goals on GCP |
| `message_type` | `string`, `null` | `complete` or `delta` when set |
| `queue_config` | `object({ input_queue_max_receive_count = optional(number, D), output_queue_max_receive_count = optional(number, D), batch_size = optional(number, 1) })` | counts ≥ 1, `batch_size` 1–1000 (Pub/Sub's pull maximum) |
| `agent_runner` | `object({ cpu = optional(string, "1"), memory = optional(string, "512Mi"), instance_count = optional(number, 1), package_path = optional(string), image_uri = optional(string), command = optional(list(string)), args = optional(list(string)), environment_variables = optional(map(string), {}) })`, `{}` | `cpu` one of `1, 2, 4, 6, 8` (the worker-pool values); when `queue_mode`, at least one of `package_path`, `image_uri`, `command` |
| `scaling_config` | `object({ enabled = optional(bool, false), min_count = optional(number, 0), max_count = optional(number, 10), backlog_target = optional(number, 10) })`, `{}` | `!enabled \|\| var.queue_mode`; `min_count <= max_count` |

- `D` mirrors AWS per flavor, field names included: `5` in containerized
  (`ak-aws/containerized/variables.tf:340,347`), `3` in serverless (`ak-aws/serverless/variables.tf:467,477`).
- **Cross-variable `validation`, not `check` blocks.** A failing `check` only warns and the apply
  continues; a `validation` that references another variable fails the plan and needs Terraform
  ≥ 1.9, which both roots already require (`containerized/main.tf:16`). AWS uses the same form
  (`ak-aws/containerized/variables.tf:270-273`). Design amendment, [§7](#7-design-amendments-for-re-review) item 4.
- The `agent_runner` command rule exists because, without its own image or command, the runner
  would run the edge image's `CMD` and serve REST instead of consuming the queue.
- Names follow AWS where AWS has the concept (`queue_mode`, `execution_mode`, `message_type`,
  `queue_config`, `agent_runner`, `scaling_config`); `instance_count` replaces ECS's
  `desired_count`, and `cpu`/`memory` are strings, as on the GCP services (`variables.tf:69-79`).

#### 5.5 Root wiring (`queue_mode.tf`, both roots)

- `module "pubsub"` and `module "agent_runner"` with `count = var.queue_mode ? 1 : 0`.
- `module "agent_runner_docker_image"` (the existing `artifact-registry` module) when
  `agent_runner.package_path` is set, with `prefix = "${var.prefix}-runner"`: the repository id is
  the prefix, so the runner needs its own (AWS does the same, `ak-aws/containerized/state.tf:109-115`).
- Runner image precedence, as on AWS (`ak-aws/containerized/queue_mode.tf:64`): its own build, then
  `agent_runner.image_uri`, then the edge's `module.docker_image.image_url`.
- **Environment.** The existing session and thread entries (`cloud_run.tf:157-172`,
  `cloud_function.tf:156-171`) move into `local.session_env`, used by both tiers. The service's
  `env` merge keeps its order, so non-queue plans are unchanged. New `local.queue_env`, merged into
  both tiers when `queue_mode`:

  | Variable | Value |
  |---|---|
  | `AK_EXECUTION__QUEUES__PUBSUB__PROJECT_ID` | `var.project_id` |
  | `AK_EXECUTION__QUEUES__PUBSUB__{INPUT,OUTPUT}_{TOPIC,SUBSCRIPTION}` | the `pubsub` module's names |
  | `AK_EXECUTION__QUEUES__PUBSUB__DLQ_SUFFIX` | the module's `dlq_suffix` |
  | `AK_EXECUTION__QUEUES__{INPUT,OUTPUT}__MAX_RECEIVE_COUNT` | `max(1, n - 1)` ([§5.2](#52-module-pubsub)) |
  | `AK_EXECUTION__QUEUES__BATCH_SIZE` | `queue_config.batch_size` |
  | `AK_EXECUTION__RESPONSE_STORE__REDIS__URL` | `local.redis_url` |
  | `AK_EXECUTION__MODE` | `var.execution_mode` |
  | `AK_EXECUTION__MESSAGE_TYPE` | `var.message_type`, when set |

  - Never `AK_EXECUTION__QUEUES__TYPE` or `AK_EXECUTION__RESPONSE_STORE__TYPE`: the app's
    `config.yaml` declares both, as on AWS (design). Without a declared `type`, the injected
    `AK_EXECUTION__QUEUES__PUBSUB__*` variables fail config load, because `_QueuesConfig.type` has
    no default (`core/config.py:628-636`).
  - Runner env = `merge(var.environment_variables, local.session_env, local.queue_env,
    var.agent_runner.environment_variables)`.
  - `AK_EXECUTION__MODE` goes to both tiers in every queue-mode deployment, as on AWS serverless
    (`ak-aws/serverless/state.tf:633-634`), since the edge's route and the runner's reply shape
    must agree.
- **Edge in queue mode:**
  - `resources { cpu_idle = var.queue_mode ? false : null }`. `null` leaves the attribute unset,
    so non-queue plans are unchanged. Explicit `false` keeps the response-handler thread running
    between requests whatever the provider's default becomes (amendment item 5).
  - IAM on the edge's existing service account: `roles/pubsub.publisher` + `roles/pubsub.viewer`
    on the input topic; `roles/pubsub.subscriber` + `roles/pubsub.viewer` on the output
    subscription; `roles/pubsub.publisher` + `roles/pubsub.viewer` on the output dead-letter topic.
- **API Gateway in queue mode** (`state.tf:53-71`):
  - drop the `chat-multipart` default route: the pipeline serves multipart only on `in_memory`
    (`pipeline/request_handler.py:366-369`). AWS drops it too (`ak-aws/containerized/state.tf:45-48`);
  - add `GET <base>/chat` → `/api/v1/chat` when `execution_mode == "rest_async"`: the poll route
    (`pipeline/request_handler.py:365`). AWS adds the same (`ak-aws/containerized/api_gateway_async.tf:5-25`).
- **API Gateway builder fix** (`api_gateway.tf`, both roots). `openapi_paths_flat` is keyed by path
  (`api_gateway.tf:8-16`), so a GET and a POST on one path collide ("Duplicate object key"), and the
  per-method maps are joined with a shallow `merge` (`api_gateway.tf:137-144`). The builder is
  changed to key operations by method and path and to group them per path, emitting one path object
  holding every method plus at most one `options`.
  - Requirement: for every endpoint map that renders today (one method per path), the rendered
    `openapi.json` is byte-identical, so `api_config_id` (`md5` of the spec, `api_gateway.tf:222-238`)
    does not change and no gateway config is replaced.
- **Providers.** `google` and `google-beta` floors rise from `>= 6.8.0` to `>= 6.37.0` in both
  roots' `main.tf`, `common/versions.tf` and the new modules. The examples' `providers.tf` keep
  `>= 6.8.0`; CI runs `terraform init -upgrade` (`.github/scripts/run_single_test.py:640`).
- **APIs.** `pubsub.googleapis.com` (and `parametermanager.googleapis.com` for CREMA) are added to
  the manual enablement lists in `containerized/run.md:21-25` and `common/run.md:24-28`. ak-gcp
  enables no API through Terraform today, and this change keeps that.
- **Outputs.** `input_topic`, `output_topic`, `agent_runner_worker_pool` (null outside queue mode).

### 6. Cloud Run entry point (`deployment/gcp/akcloudrun.py`)

```python
@classmethod
def run(cls, handlers: list[RESTRequestHandler] | None = None) -> None:
    """Start the pipeline's IO process on Cloud Run.

    On in_memory this is today's single-process topology. On a broker transport it is the edge:
    the REST API plus the response handler; the agent runner is its own worker pool running
    AgentRunner.run().
    """
```

1. Refuse, with `AKConfigError`, `execution.is_websocket` or `mode == REALTIME` on a transport
   other than `in_memory` (design amendment, [§7](#7-design-amendments-for-re-review) item 1).
   The message names the reason: Cloud Run instances are not individually addressable, so replies
   cannot be pushed to the instance that holds a socket. Read through `AKConfig.get().execution`
   and `QueueTransportFactory.resolve_type()`, both before any thread starts.
2. `RESTAPI.add(cls._router)` when it has routes (unchanged, `akcloudrun.py:75-76`).
   `IOHandler` builds its app through `RESTAPI.build_app`, which includes the custom routers
   (`api/http.py:202-204`), so registered routes are served in both topologies.
3. `IOHandler.run(handlers=handlers)`.

- `RESTRequestHandler` is imported under `TYPE_CHECKING`; `IOHandler` and `RESTAPI` are imported
  inside `run`, as `RESTAPI` already is (`akcloudrun.py:72`), so importing `agentkernel.gcp` stays
  light.
- No `auth_validator` (design): REST auth stays on `GCPAuthorizer.register()`, which reaches every
  route of the app `IOHandler` serves (`deployment/gcp/akauthorizer.py:20-29`, `api/http.py:207-236`).
- The runner tier needs no GCP class: its entry point is `agentkernel.pipeline.AgentRunner.run()`.

### Consumer changes

- **`KafkaTransport`**: no code change. It inherits the new bookkeeping resolution step
  (behavioural change 2).
- **`IOHandler`, `AgentRunner`, `ResponseHandler`, `ConsumerLoop`**: no change. Verified:
  - they reach the transport only through `QueueTransportFactory` and the `TransportConsumer` ABC
    (`agent_runner.py:172-186`, `consumer.py:106-127`);
  - the broker topology checks already demand a shared response store for REST modes
    (`io_handler.py:239-256`) and for A2A/MCP (`io_handler.py:257-268`);
  - `AgentRunner.run()` already refuses `in_memory` (`agent_runner.py:195-196`).
- **Sandbox queue broker**: gets `pubsub` through the factory seam with no change. Bookkeeping
  still reads `execution.*`, not `sandbox.broker.*`, exactly as for Kafka today (non-change).
- **`ScheduleManager`**: no change. It refuses a `schedule` block on `pubsub` with both built-in
  providers (`schedule/manager.py:318-370`; `eventbridge` supports only `sqs`,
  `schedule/provider/eventbridge.py:56`).
- **Examples `gcp-*/openai`**: unchanged. They call `RESTAPI.run(...)` themselves and never reach
  `CloudRun`.

### Config changes

- **Added:** `_PubSubQueueConfig` and `_QueuesConfig.pubsub` ([§3](#3-configuration-coreconfigpy)),
  and `pubsub` in the `type` description.
- **Unchanged:** every existing field, default and description. No field is renamed or removed.
- **Existing YAML and `AK_*` variables** load exactly as before: the new block is optional and
  defaults to `None`.
- **Implicit enablement:** a Redis or Valkey response store now also selects durable bookkeeping
  ([§2.1](#21-resolution-order)). No flag.

### Behavioural changes

1. **`CloudRun.run()` on a broker transport starts the edge** instead of serving the direct
   handler. Intentional: today `RESTAPI.run()` serves `AgentRESTRequestHandler`
   (`api/http.py:108-115`), so the agent runs inside the request and the queue is unused. With no
   arguments on `in_memory` it is identical to today: `RESTAPI.run()` itself hands that case to
   `IOHandler.run()` (`api/http.py:99-106`).
   - Consequence: on a broker transport, `CloudRun.run()` now needs a shared response store, which
     `IOHandler` already enforces (`io_handler.py:243-248`).
   - Consequence: A2A and agent MCP now work through `CloudRun.run()` on a broker transport, where
     `RESTAPI.run()` refused them (`api/http.py:110`, `151-169`).
2. **Kafka gets durable bookkeeping from a Redis or Valkey response store** when sessions live
   elsewhere. Intentional (design): it is what the warning asked operators to provide.
3. **`CloudRun.run()` refuses `async` and `realtime` on a broker transport** (amendment item 1).
   Today such a deployment starts and fails per message.
4. **`BookkeepingStore` gains two abstract methods.** Internal API only (no BYO branch).

**Non-changes:**

- `QueueMessage`, `QueueTransport`, `TransportConsumer` and `ConsumerLoop` signatures.
- Bookkeeping key layout for Kafka (`ak:qattempts:`, `ak:qdedup:` and their TTLs).
- `CloudRun.register()`, `GCPAuthorizer`, and the public exports of `agentkernel.gcp`.
- Single-instance GCP Terraform plans with `queue_mode = false`.
- Data written before the change: no persisted layout changes, so it reads back identically.

### 7. Design amendments for re-review

1. **`CloudRun.run()` refuses `async` and `realtime` on a broker transport.** The design says
   `IOHandler` already refuses them (`design.md` Non-goals, citing `io_handler.py:88-96`). It does
   only for `async` on a session backend without a shared connection store (Firestore raises,
   `core/session/firestore.py:114-123`). `async` with Redis sessions passes that check, and
   `realtime` is never checked there. Terraform's `check` block covers Terraform deployments only.
2. **The design's Non-goal citation is corrected** in `design.md` to match item 1.
3. **Unary-pull cancellation stall** ([§1.5](#15-receive-side)). Kept as designed, with the 10 s
   subscription deadline as mitigation. If the live run shows stalls are frequent, the fallback is
   a streaming pull per consumer, which the client library leases and orders itself. That would be
   a design change, not an implementation detail.
4. **Terraform guards are cross-variable `validation`s, not `check` blocks** ([§5.4](#54-root-variables-both-roots)).
   The design says `check` blocks "fail at `terraform plan`"; a failing `check` only warns.
5. **The `cpu_idle` motivation is probably wrong.** The provider documents `cpu_idle` as "True by
   default if the parent `resources` field is not set. However, if `resources` is set, this field
   must be explicitly set to true to preserve the default behavior." Both services set `resources`
   without `cpu_idle` (`cloud_run.tf:122-127`, `cloud_function.tf:122-127`), so today's services
   likely already keep CPU allocated. The requirement stands (explicit `cpu_idle = false` on the edge
   in queue mode); `design.md`'s Motivation bullet is corrected. Confirm on a deployed service
   (`run.googleapis.com/cpu-throttling` annotation) in plan iteration 5.
6. **The API Gateway builder must change** ([§5.5](#55-root-wiring-queue_modetf-both-roots)) for
   `rest_async`, a supported mode in the design: the builder cannot hold GET and POST on one path.
7. **New validation:** in queue mode the runner needs its own image or `command`
   ([§5.4](#54-root-variables-both-roots)).
8. **Dead-letter IAM is per consumer:** each tier publishes only to the dead-letter topic of the
   queue it consumes. The design says "both publish to the dead-letter topics".

## Error handling

| Failure | Where it surfaces |
|---|---|
| `pubsub` extra missing | `require_extra` → `ImportError` naming `pip install agentkernel[pubsub]` and the config path, at factory time |
| `execution.queues.pubsub` block missing | `AKConfigError` from the factory |
| No project (no `project_id`, no ADC project) | `AKConfigError` on first use naming `<config_path>.pubsub.project_id` |
| Topic, dead-letter topic or subscription missing (`auto_provision: false`) | `AKConfigError` naming the object. On the receive side this fails the consumer thread at startup and `ThreadRunner` exits the process; on the send side the request fails |
| Subscription without ordering | `AKConfigError` at `create_consumer`, saying to recreate it |
| Verify call denied (`PermissionDenied`) | Propagates unchanged: the IAM grant is missing ([§5](#5-terraform)) |
| Publish error or timeout | Raised from `send` after `resume_publish`; the REST route answers 500, a runner's output send is retried by redelivery |
| Pull error other than `DeadlineExceeded` | Raised from `fetch`; `ConsumerLoop` logs and backs off 5 s |
| Ack / mark-acked / clear-attempts failure | Logged, never raised (rule 6) |
| Nack failure | Logged by `ConsumerLoop._safe_nack`; the message returns at its deadline |
| Lease renewal failure | WARNING, retried next tick |
| Dead-letter publish failure | ERROR "copy lost"; the original is acked anyway |
| Undecodable message | Copied to the dead-letter topic, acked, ERROR |
| Bookkeeping Redis unreachable during serve | The driver's 3-retry back-off, then the exception propagates from `fetch`; `ConsumerLoop` backs off. The messages keep their leases until `ack_wait` |
| `CloudRun.run()` with `async`/`realtime` on a broker | `AKConfigError` before any thread starts |

## Testing

Run with `cd ak-py && uv run pytest`. `ak-py/build.sh:13` installs every extra but `crewai`, so the
new `pubsub` extra is present once `uv.lock` is refreshed.

### New: `tests/test_pipeline_pubsub_transport.py`

A fake broker behind the real client interface, the Kafka/NATS pattern
(`tests/test_pipeline_kafka_transport.py:37-200`):

- `FakePubSubServer`: topics, subscriptions with ordering, at most one outstanding batch per key,
  per-message ack deadlines on a **fake clock**, redelivery on deadline expiry and on deadline 0,
  and the cascade (redelivering a message redelivers every later message for its key, acked ones
  included, research §1).
- `FakePublisherClient` / `FakeSubscriberClient` implement exactly the calls the transport makes
  (`publish` returning a future, `resume_publish`, `get_topic`, `create_topic`, `pull`,
  `acknowledge`, `modify_ack_deadline`, `get_subscription`, `create_subscription`, `close`).
  An empty `pull` raises `DeadlineExceeded`, as a real one does when its deadline passes.
- Fixture patches `agentkernel.pipeline.transport.pubsub.pubsub_v1.PublisherClient` and
  `.SubscriberClient`, and calls `PubSubTransport.reset()` before and after.

| Class | Asserts |
|---|---|
| `TestEnvelopeCodec` | Round trip; 150 attributes and an 8192-byte value survive byte for byte; only `ak-envelope` is a Pub/Sub attribute; `group_id` ↔ ordering key with `None` ↔ `""`; missing marker or bad JSON → `ValueError` |
| `TestSend` | Ordering key and data; `{"MessageId": ...}`; a failed publish calls `resume_publish` then raises, and the next send for that key succeeds; a timeout raises |
| `TestOneKeyAtATime` | Several messages for one key in **one** pull are served one per fetch, in order; another key is served beside them; keyless messages are served together |
| `TestCascade` | An acked message redelivered by a cascade is acked without being served; a lost ack (the fake drops it) is dropped the same way |
| `TestDedup` | A second message with the same `dedup_id` is acked and dropped; the same `dedup_id` on the other subscription is **not** (the reply case) |
| `TestReceiveCount` | Exact across nacks; exact across a consumer restart sharing one `InMemoryBookkeepingStore` (the durable case); `delivery_attempt` is ignored |
| `TestNack` | Deadline 0 for the message and every held message of its key; other keys keep theirs |
| `TestDeadLetter` | Copy published to `<topic>-dlq` with `ak-error` and the original data, then acked; a failed copy logs at ERROR and still acks |
| `TestSupersede` | A pulled message for a key with stale local state drops that state and is served |
| `TestQuarantine` | An undecodable message is copied to the dead-letter topic, acked, never served |
| `TestLeases` | The first deadline is set at fetch to `min(60, ack_wait)`; `tick()` renews held and in-flight messages; renewal stops once `ack_wait` has passed (injected `clock`); a failed renewal warns and is retried; `close()` stops the thread and releases held messages |
| `TestProvisioning` | Verify: missing topic, subscription or dead-letter topic → `AKConfigError` naming it; ordering off → `AKConfigError`. Create: ordering, ack deadline 10, dead-letter policy with the factory's attempts, a dead-letter subscription; `AlreadyExists` accepted; once per process |
| `TestProject` | `project_id` wins; else `google.auth.default()` (patched); neither → `AKConfigError` |
| `TestFactory` | Config → constructor arguments; `max_delivery_attempts` clamped to 5–100; missing block → `AKConfigError` naming `execution.queues.pubsub`; an explicit sandbox-style block flows through; missing extra → the `require_extra` message (patch `builtins.__import__` for `agentkernel.pipeline.transport.pubsub`) |
| `TestPubSubTransportContract(QueueTransportContract)` | The full contract with **no** opt-outs; `force_redelivery` advances the fake clock past every deadline |

### Changed: `tests/test_pipeline_bookkeeping.py`

- `_StoreContract` (`:58`): `mark_acked` / `was_acked`; expiry with `InMemoryBookkeepingStore(dedup_ttl=0)`.
- `TestRedisLikeBookkeepingStore`: the third driver writes `ak:qacked:<key>`; the two-argument
  construction (`:113-116`, unchanged) falls back to `ak:qdedup:acked:<key>`.
- `TestFactorySelection._cfg` (`:155-165`) gains an `execution` attribute whose `response_store` is
  `None` by default; the patch target `agentkernel.core.config.AKConfig.get` is unchanged. New cases:
  a Redis or Valkey response store gives `RedisLikeBookkeepingStore` with sessions on `firestore`;
  sessions win when both are set; a response store without its block falls back; the fallback
  warning names `execution.response_store.type`.

### New: `tests/test_gcp_cloudrun.py`

There are no `deployment/gcp` tests today. Patch `agentkernel.pipeline.io_handler.IOHandler.run`
and `agentkernel.core.config.AKConfig.get` (a real `_ExecutionConfig`, per the testing conventions):

- `in_memory`, no arguments → `IOHandler.run(handlers=None)`;
- handlers are passed through unchanged;
- a route added with `CloudRun.register` reaches `RESTAPI.add` (patched) before `IOHandler.run`;
- broker transport + `async`, and + `realtime` → `AKConfigError` before `IOHandler.run`;
- `in_memory` + `async` reaches `IOHandler.run` (its own validator check applies);
- importing `agentkernel.gcp` does not load `agentkernel.pipeline.io_handler` (the `sys.modules`
  pattern of `tests/test_aws_lazy_exports.py`).

### Changed elsewhere

- `tests/test_config.py`: the `pubsub` block from YAML and from `AK_EXECUTION__QUEUES__PUBSUB__*`;
  its defaults; injected `pubsub` variables with no declared `type` fail at load.
- `tests/test_packaging_extras.py`: the `pubsub` extra pins `google-cloud-pubsub`.
- `tests/test_transport_contract_live.py`: `TestPubSubTransportContractLive`, gated on
  `AK_TEST_PUBSUB_EMULATOR_HOST` (copied into `PUBSUB_EMULATOR_HOST` by a `monkeypatch` fixture,
  since the clients read it at construction):
  - project `ak-contract`, names `ct-<uuid8>-in/out`, `auto_provision=True`, an injected
    `InMemoryBookkeepingStore`, `ack_wait = 3.0`, `fetch_wait = 10.0`;
  - plus `test_message_id_is_stable_across_redelivery`, which confirms research §9 (bookkeeping is
    keyed by it).
- `.github/workflows/test-reusable.yaml` `transport-integration-tests` (`:160-211`): start the
  emulator with `docker compose -f examples/transport/pubsub/docker-compose.yaml up -d --wait pubsub`,
  set `AK_TEST_PUBSUB_EMULATOR_HOST: localhost:8085`, and add its `down -v`.

### Terraform

- `terraform fmt -check` and `terraform validate` on both roots and both new modules.
- `queue_mode = false`: `terraform plan` for `examples/gcp-serverless/openai` and
  `examples/gcp-containerized/openai` against an existing deployment shows **no changes**
  (the env refactor, the `cpu_idle = null` path and the API Gateway builder are all no-ops).
- `queue_mode = true` with `execution_mode = "async"`, or without `create_redis_cluster`, or with no
  runner image or command → `terraform plan` fails with the validation message.

### End to end

- `examples/transport/pubsub/` (the `ak-dev-new-queue-transport` checklist): two processes on the
  emulator, `app_test.py` covering `rest_sync`, a multi-turn session, and a poison message reaching
  the dead-letter subscription. Registered in `.github/test-config.yaml` (`type: containerized`).
- `examples/gcp-serverless/openai-queue-mode/`: weekly entry in
  `.github/integration-test-config.yaml` (`type: gcp-serverless`). Its test tolerates cold starts
  (the retry pattern of `examples/gcp-serverless/openai/serverless_test.py:30-41`) and runs a
  multi-turn `rest_sync` conversation. The CI project needs `pubsub.googleapis.com` enabled.
