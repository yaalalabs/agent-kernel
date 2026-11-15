# #887: Queue mode on Azure — Implementation Spec

How the approved [design](design.md) is built: one `servicebus` transport behind the existing
`QueueTransport` seam, one config sub-block, a `queue_mode` switch in `ak-azure/containerized`, a weekly
example, and the docs and skills that list transports. Requirements, decisions and non-goals live in
`design.md`; this document only adds how.

_Evidence at `develop` @ `57a9c10b`. Paths are relative to `ak-py/src/agentkernel/` unless they start with a
top-level folder._

## Design amendments

Found while detailing; each tightens the design rather than changing scope. `design.md` is updated to match.

1. **KEDA scale rule auth is verified.** azurerm `v5.11.0` has `identity_id` on `custom_scale_rule`
   (`CustomScaleRule.IdentityID`, `internal/services/containerapps/helpers/container_apps.go:3108`). No SAS
   fallback is needed, so namespace local auth is always off (decision 3 and 4 caveats removed).
2. **The live contract class lives in the example, not in `ak-py/tests/`.** The weekly harness runs the
   example's own pytest after deploy (`.github/scripts/run_single_test.py:710-758`); `ak-py` tests never run
   there. `QueueTransportContract` ships in the package (`pipeline/testing.py:20`), so the example subclasses
   it directly. Decision 5 is otherwise unchanged.
3. **No `.github/test-config.yaml` entry.** That file holds local e2e runs (`.github/test-config.yaml:5-7`);
   Azure examples are registered only in `.github/integration-test-config.yaml` (`:105-108`).
4. **More docs surfaces** than the design listed, per `ak-dev-new-queue-transport` Step 6: the queue mode
   guide and the docs-site inventories.
5. **Deliberate departures from `ak-dev-new-queue-transport`**: no `examples/transport/servicebus/` compose
   stack and no per-PR live run (decision 5: no emulator), and no Helm wiring (design Non-goal).
6. **Found by `terraform plan` in iteration 3** (azurerm `v5.11.0`): the namespace is `<prefix>-queues`, not
   `-sb` (a reserved suffix); `identity_id` is `"System"`; the runner holds Data Owner, not Data Receiver, on
   `input` so the KEDA scaler can read the queue length; Terraform injects no `*__TYPE` env (AWS parity).

## Design

### 1. `pipeline/transport/servicebus.py`

```python
SERVICEBUS_MAX_WAIT_SECONDS = 20.0  # fetch slice; idle receive links are re-attached once per slice
SESSION_REUSE_WAIT_SECONDS = 0.5    # how long a held session is polled before it is released


@dataclass
class _HeldSession:
    """One accepted session: its receiver, and whether a message from it is still unsettled."""
    receiver: ServiceBusReceiver
    in_flight: ServiceBusReceivedMessage | None = None


class ServiceBusTransportConsumer(TransportConsumer):
    """Session-locked consumer over one queue. Owns its client: SDK clients are not thread-safe."""

    fetch_wait_slice_seconds = SERVICEBUS_MAX_WAIT_SECONDS

    def __init__(self, client: ServiceBusClient, queue_name: str, ack_wait: float): ...
    def fetch(self, batch_size: int, wait_seconds: float) -> list[QueueMessage]: ...
    def ack(self, message: QueueMessage) -> None: ...          # complete_message, keep the session for reuse
    def nack(self, message: QueueMessage) -> None: ...         # abandon_message, release session
    def dead_letter(self, message: QueueMessage) -> None: ...  # dead_letter_message, release; never raises
    def close(self) -> None: ...                               # close receivers, renewer, client

    @staticmethod
    def _to_envelope(received: ServiceBusReceivedMessage, session_id: str) -> QueueMessage: ...


class ServiceBusTransport(QueueTransport):
    """Azure Service Bus transport: two session-enabled queues, the SQS FIFO model on Azure."""

    def __init__(self, input_url: str, output_url: str, ack_wait: float, connection_string: str | None = None,
                 config_path: str = "execution.queues"): ...
    def send(self, queue: QueueName, message: QueueMessage) -> None: ...
    def create_consumer(self, queue: QueueName) -> ServiceBusTransportConsumer: ...
    def _new_client(self) -> ServiceBusClient: ...  # connection string, else namespace + DefaultAzureCredential

    @staticmethod
    def parse_entity_url(url: str, field: str) -> tuple[str, str]: ...  # (namespace FQDN, queue name)
```

Rules:

1. **Addressing.** `parse_entity_url` accepts `https://<host>/<queue>` (also `sb://`), one path segment, and
   raises `AKConfigError` naming `field` otherwise. Both URLs must share one host, else `AKConfigError`. With
   `connection_string` set, the namespace comes from the connection string and only the queue names are
   taken from the URLs.
2. **Auth.** No connection string: `ServiceBusClient(fully_qualified_namespace, DefaultAzureCredential())`.
   One credential per transport, shared by its consumers (credentials are thread-safe).
3. **Send side.** One lazily built client per transport and one sender per queue, both built and used under
   one `threading.Lock` (senders are not thread-safe; `send` must be safe from any thread, `base.py:10`).
   `send` builds `ServiceBusMessage(body, session_id=..., message_id=..., application_properties=...)`:
   - `session_id = group_id or str(uuid4())`. The pipeline always sets it (`pipeline/request_handler.py:203`,
     `pipeline/producer.py:47`); the fallback keeps an ungrouped message deliverable on a session queue.
   - `message_id = dedup_id or str(uuid4())`.
   - Returns `None`; no caller reads the send result off AWS (`pipeline/producer.py:50` coerces it to `{}`).
4. **Receive side: one in flight per session.** A consumer holds a `dict[str, _HeldSession]`. `fetch`, within
   `wait_seconds` total:
   1. Drops held sessions whose lock has passed (`receiver.session.locked_until_utc`), closing their receivers.
   2. For each held session with nothing in flight: one `receive_messages(1, min(SESSION_REUSE_WAIT_SECONDS,
      remaining))`. A message is kept in flight; an empty receive releases the session.
   3. While fewer than `batch_size` messages: `get_queue_receiver(session_id=NEXT_AVAILABLE_SESSION,
      max_wait_time=wait)`, where `wait` is `remaining` until the fetch holds a message and then
      `min(SESSION_REUSE_WAIT_SECONDS, remaining)`, so a batch returns promptly instead of waiting out the
      long poll for sessions that never come; `OperationTimeoutError` ends the loop. Receive one message
      from the new session; an empty session is released.
   4. Each accepted session is registered once with the consumer's `AutoLockRenewer`
      (`max_lock_renewal_duration = 2 * ack_wait`), and step 2 reuses a held session only while it is
      younger than `ack_wait` (older ones are released and re-accepted). The SDK counts the ceiling from the
      session's accept (`_session_start`, `azure/servicebus/_common/utils.py:233-239`), so this gives every
      message a full `ack_wait`. Registering per message instead would leave one self-re-enqueuing renew
      task per message, and a long delta stream would renew one session hundreds of times at once.
      A receive error on a held session releases it.
   - Sessions with an unsettled message are never polled, which is what keeps `m2` behind `m1`
     (`pipeline/testing.py:96-107`). `ConsumerLoop` settles each message before the next fetch
     (`pipeline/consumer.py:114-126`), so reuse is the normal path for back-to-back turns and delta chunks.
5. **Settle.** `ack` / `nack` / `dead_letter` settle through the held receiver found by the envelope's
   `group_id`. `ack` and a successful `dead_letter` keep the session held for reuse (rule 4); `nack`, and
   any settle failure, close that receiver and forget the session (a released session is free for any
   consumer).
   `dead_letter` passes `reason="max_receive_count exceeded"` and swallows and logs failures, the NATS rule
   (`pipeline/transport/nats.py:150-165`): the queue's `max_delivery_count` is the backstop.
6. **Envelope.** `body`: the message body bytes decoded as UTF-8. `attributes`: `application_properties`
   with bytes keys and values decoded to `str`. `group_id`: the session id. `receive_count`: `delivery_count + 1` (the SDK returns the AMQP header count,
   which counts prior deliveries only; the live contract confirms it).
   `message_id`: `str(sequence_number)`. `native`: the received message.
7. **Capacity.** `check_consumer_capacity` is not overridden: sessions have no partition ceiling.
8. **No class-level caches**, so no `reset()` classmethod (unlike `NatsTransport.reset`).
9. **Logger** `ak.pipeline.transport.servicebus`.

### 2. Factory: `pipeline/transport/base.py`

- `_BUILTIN_TYPES` (`:103`) gains `"servicebus"`; the class docstring and the unknown-type error list follow.
- New branch after `nats`:
  ```python
  if transport_type == "servicebus":
      with require_extra("azure", f"{config_path}.type: servicebus"):
          from .servicebus import ServiceBusTransport
      # both URLs required, exactly as the sqs branch (:140-145)
      sb = getattr(queues, "servicebus", None)
      return ServiceBusTransport(input_url, output_url,
                                 ack_wait=sb.ack_wait if sb else DEFAULT_ACK_WAIT_SECONDS,
                                 connection_string=sb.connection_string if sb else None,
                                 config_path=config_path)
  ```
- The sandbox broker's `sandbox.broker.queue` block resolves through the same branch (#503 seam); errors
  name `config_path`.

### 3. Consumer changes

- None. `RequestProducer`, `AgentRunner`, `StreamAgentRunner`, `ResponseHandler`, `IOHandler` and
  `ConsumerLoop` speak only the ABCs. Verified unchanged: `AgentRunner.run` refuses only `in_memory`
  (`pipeline/agent_runner.py:196-197`); `IOHandler.run` starts the output consumer on a broker transport
  (`pipeline/io_handler.py:131`); `ResponseStoreFactory` requires a shared store on any non-`in_memory`
  transport (`pipeline/response_store/factory.py:50-60`).

### 4. Config changes: `core/config.py`

```python
class _ServiceBusQueueConfig(BaseModel):
    ack_wait: float = Field(default=300.0, description=(
        "Seconds a received message's session lock is renewed while the agent works. Past it the lock "
        "lapses and the message is redelivered (within the queue's lock duration). Keep it above your "
        "longest agent turn, or a slow turn runs twice."))
    connection_string: str | None = Field(default=None, description=(
        "Service Bus connection string, for the local emulator and development only. Unset uses Azure "
        "managed identity (DefaultAzureCredential) against the namespace in input.url / output.url."))
```

- `_QueuesConfig` (`:771`) gains `servicebus: _ServiceBusQueueConfig | None = Field(default=None,
  description="servicebus transport settings")`; its `type` description lists `servicebus`.
- `_InputQueueConfig.url` / `_OutputQueueConfig.url` (`:665`, `:681`) descriptions become "Input (Output)
  queue URL (sqs: queue URL; servicebus: `https://<namespace>.servicebus.windows.net/<queue>`)".
- Env: `AK_EXECUTION__QUEUES__SERVICEBUS__ACK_WAIT`, `AK_EXECUTION__QUEUES__SERVICEBUS__CONNECTION_STRING`
  (standard `AK_` nesting). `connection_string` can be kept out of the YAML with the existing `<file:...>` reference (`core/util/config_yaml_util.py:39-44`).
- Old YAML and env load unchanged: the new block is optional, no default or type changes.

### 5. Dependencies: `ak-py/pyproject.toml`

- `azure` extra (`:83-87`) gains `azure-servicebus` and `azure-identity`, each pinned to its current major
  (checked on PyPI at implementation, house range style `>=x.y,<next-major`). `uv.lock` regenerated.

### 6. Terraform: `ak-deployment/ak-azure/containerized`

New file `queue_mode.tf`, all resources `count = var.queue_mode ? 1 : 0`:

| Resource | Settings |
|---|---|
| `azurerm_servicebus_namespace.queues` | `"${var.prefix}-queues"` (Service Bus rejects names ending in `-sb`, caught by `terraform plan`), `sku = "Standard"`, `local_auth_enabled = false`, `minimum_tls_version = "1.2"` |
| `azurerm_servicebus_queue.input` / `.output` | `requires_session = true`, `requires_duplicate_detection = true`, `duplicate_detection_history_time_window = "PT5M"`, `lock_duration = "PT1M"`, `max_delivery_count = local.max_receive_count + 1`, `dead_lettering_on_message_expiration = true` |
| `azurerm_container_app.agent_runner` | same environment, registry and image as `app`; `command = var.agent_runner_command`; no `ingress`; system identity; `termination_grace_period_seconds = 300`; `min/max_replicas` from the existing variables; `custom_scale_rule` `azure-servicebus` with `metadata = { namespace, queueName = "input", messageCount = "5" }` and `identity_id = "System"` (the provider accepts only that exact casing or a user-assigned identity ID); env and secret refs shared with the edge through `local.app_env` / `local.env_secret_refs` |
| `azurerm_role_assignment` ×4 | edge: Data Sender on `input`, Data Receiver on `output`; runner: **Data Owner** on `input` (the KEDA scaler reads queue runtime properties, a manage operation on Service Bus), Data Sender on `output` (queue scope) |

- `locals` in `queue_mode.tf`:
  - `max_receive_count = 3` (the AK default, `core/config.py:666-668`), injected as
    `AK_EXECUTION__QUEUES__{INPUT,OUTPUT}__MAX_RECEIVE_COUNT` so the broker ceiling stays one above it.
  - `queue_env`: `AK_EXECUTION__QUEUES__INPUT__URL` / `OUTPUT__URL` (`https://${namespace}.servicebus.windows.net/<queue>`),
    the two receive counts and the response-store URL by secret reference. Coordinates only, like
    `ak-aws/containerized/modules/rest-service/main.tf:31-40`: `execution.queues.type` and
    `execution.response_store.type` come from the app's `config.yaml`.
  - `messageCount = "5"` matches `no_of_consumers`' default (`core/config.py:669-670`); comment says so.
- `container_app.tf` edits to `app` (the edge), all gated on `var.queue_mode`:
  - A `redis-url` secret holding `local.full_redis_url`; `AK_EXECUTION__RESPONSE_STORE__REDIS__URL` and the
    existing `AK_SESSION__REDIS__URL` reference it (see Behavioural change 2).
  - Merge `local.queue_env` into the env map; `termination_grace_period_seconds = 60` (covers one
    20-second fetch slice plus in-flight output handling).
- `variables.tf`:
  - `queue_mode` (bool, default `false`; description mirrors `ak-aws/containerized/variables.tf:256-260`).
  - `agent_runner_command` (list(string), default `["python", "app_agent_runner.py"]`, the Helm default,
    `ak-deployment/ak-k8s/chart/values.yaml:172`).
  - A `validation` on `queue_mode`: `!var.queue_mode || var.create_redis_cluster`, message naming the response
    store. Terraform 1.9+ cross-variable validation is within the module's `required_version` (`main.tf:2`).
- `outputs.tf`: `servicebus_namespace` (FQDN, null when off), `servicebus_input_queue`, `servicebus_output_queue`,
  `agent_runner_name`.
- `ak-azure/serverless` and the `ak-common` modules: no changes. Example version pins are not hand-edited
  (release chore bumps them).

### 7. Example: `examples/azure-containerized/openai-queue-mode/`

- Copied shape from `openai-cosmos` and `examples/k8s/openai-queue-mode/`: `app_agents.py` (the triage
  agents), `app_io_handler.py` (`IOHandler.run()`), `app_agent_runner.py` (`AgentRunner.run()`),
  `config.yaml` (`execution.queues.type: servicebus`, `execution.mode: rest_sync`, `session.type: cosmosdb`),
  `build.sh`, `pyproject.toml` (`agentkernel[openai,api,azure]`), `README.md`, `test-config.yaml`.
- `deploy/`: `main.tf` calls `ak-containerized/azurerm` with `queue_mode = true`, `create_redis_cluster = true`,
  `create_cosmosdb_cluster = true`; Dockerfile `CMD ["python", "app_io_handler.py"]`; an extra
  `azurerm_role_assignment` granting the deploying principal (`data.azurerm_client_config.current`)
  **Azure Service Bus Data Owner** on the namespace, for the contract test; outputs `agent_invoke_url` and
  `servicebus_namespace`.
- `app_test.py`: `rest_sync` multi-turn on one session, and `rest_async` submit then poll, both through APIM.
- `servicebus_contract_test.py`: `QueueTransportContract` subclass, skipped unless
  `AK_TEST_SERVICEBUS_NAMESPACE` is set. Per test it creates two uniquely named session-enabled,
  duplicate-detecting queues with `lock_duration = 5s` through `ServiceBusAdministrationClient`, and deletes them in
  teardown. `ack_wait = 0.2`; `force_redelivery` sleeps past the 5-second lock.
- `.github/scripts/run_single_test.py` `test_azure_deployment`: also read the optional `servicebus_namespace`
  output and export it as `AK_TEST_SERVICEBUS_NAMESPACE` when present (other Azure examples have no such
  output and are unaffected).
- `.github/integration-test-config.yaml`: a weekly `azure-containerized` entry after `:106-108`.

### Behavioural changes

1. New transport type `servicebus`. Intentional; additive.
2. In `ak-azure/containerized` with `queue_mode = true` only, the Redis URL (which embeds the access key,
   `ak-azure/common/modules/redis/outputs.tf:14-15`) reaches the app through a Container Apps secret instead of
   a plain env value (`container_app.tf:100-105`). Intentional: the queue path adds a second consumer of the
   URL, and a plain env value is readable by anyone with read access to the app. `queue_mode = false` plans
   identically to today.

**Non-changes:** no public export, no ABC signature, no existing config field or default, no `ak-azure/serverless`
or Functions code, no stored data layout (sessions, response records), no Helm chart file.

## Error handling

| Failure | Where it surfaces |
|---|---|
| `azure` extra missing | `require_extra` → `ImportError` naming the extra, at transport creation (startup) |
| A URL missing, malformed, or the two on different namespaces | `AKConfigError` naming `<config_path>.input.url` / `.output.url`, at startup |
| Auth or network failure on `send` | `ServiceBusError` subclasses propagate; the REST handler returns its existing 500 |
| Message over the Standard tier's 256 KB | `MessageSizeExceededError` propagates from `send` (SQS parity: same limit) |
| No session available within the wait | `OperationTimeoutError` caught in `fetch`; returns what it has (possibly `[]`) |
| Other `ServiceBusError` in `fetch` | propagates; `ConsumerLoop` logs and backs off (`pipeline/consumer.py:115-120`) |
| Session lock lost before settle | `ack`/`nack` raise `SessionLockLostError` after forgetting the session; the loop's nack path logs it; the broker redelivers (at-least-once, #440) |
| `dead_letter` failure | logged and swallowed; `max_delivery_count` dead-letters on the next delivery |

Concurrency: one consumer per thread (`base.py:42-44`); consumer state is instance-only. The transport's send
path is the only shared state and sits behind one lock. `AutoLockRenewer` runs its own executor thread per
consumer and is closed in `close()`.

Per-operation cost: one receive call per settled message on a reused session; one session accept per new
session; one idle accept per consumer per 20-second slice. Lock renewal is one call per locked session about
every `lock_duration / 2`.

## Testing

- **New `ak-py/tests/test_pipeline_servicebus_transport.py`**:
  - A fake behind the SDK surface the transport uses (`ServiceBusClient`, sender, session receiver with
    `session.locked_until_utc`, `AutoLockRenewer`), installed by monkeypatching the names in
    `agentkernel.pipeline.transport.servicebus`, the `FakeSQSClient` pattern
    (`ak-py/tests/test_pipeline_sqs_transport.py:214-313`). The fake models sessions, duplicate detection,
    `delivery_count` on abandon and on lock expiry, and lock expiry at the renewer's ceiling.
  - `TestServiceBusTransportContract(QueueTransportContract)` over the fake, no opt-outs.
  - Unit tests: send mapping (session id, message id, properties, fallbacks); envelope decoding of bytes
    properties; session reuse after ack (one accept for two back-to-back messages); a held session with an
    unsettled message is not polled; lost-lock pruning; `dead_letter` swallowing a failure; `close()` closes
    every receiver, the renewer and the client.
  - Factory: builds from a block; both URLs required; malformed and cross-namespace URLs; missing extra
    (`require_extra` patched); `connection_string` path vs credential path.
- **`ak-py/tests/test_pipeline_factory_seams.py`**: one case that an explicit `servicebus` block threads
  through `create_consumer` and its errors name the caller's block (`:61-82` pattern).
- **Config**: `ak-py/tests/test_config*.py` gains a load of `execution.queues.servicebus` from YAML and env.
- **Live**: the example's `servicebus_contract_test.py`, weekly.
- **Terraform**: `terraform fmt -check` and `terraform validate` in `ak-azure/containerized`; `terraform plan`
  of the example with `queue_mode = true` and `false` (the latter diffed against today's plan: no changes).
- Command: `cd ak-py && uv run pytest tests/test_pipeline_servicebus_transport.py tests/test_pipeline_factory_seams.py`;
  then `make lint-check-all`.
