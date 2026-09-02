# #503: Sandbox queue broker: transport-agnostic queue-decoupled sandbox execution (Implementation Spec)

Implements the approved [design.md](design.md): a `queue` broker flavor whose client submits
`ExecutionRequest`s over any #495 `QueueTransport`, a `QueueBrokerWorker` runnable that consumes
them, drives `BrokerWorkerCore`, and returns completions over the block's output queue, where
the worker's own output loop persists them to the pipeline response-store family,
and the `kubernetes` sandbox provider both target deployments execute on. The one-sentence design
idea: the transport contract's per-group FIFO (`group_id = sandbox_session_id`) carries the #494
per-session serialization contract across a worker fleet, so the broker needs no distributed
locks and every existing transport works unchanged.

Requirements source: [design.md](design.md). Line references verified against `develop` at the
time of writing.

## Design

### Package layout and governing rules

```
ak-py/src/agentkernel/sandbox/broker/
├── queue.py           # QueueExecutionBroker (agent-side client flavor)
├── queue_worker.py    # QueueBrokerWorker (request + output consumer loops) + idle sweep
└── wire.py            # binary-safe (de)serialization of the broker wire models

ak-py/src/agentkernel/sandbox/providers/
└── kubernetes.py      # KubernetesSandbox + KubernetesSandboxProvider

ak-deployment/ak-k8s/chart/templates/
├── deployment-sandbox-worker.yaml   # optional tier (sandboxWorker.enabled)
├── serviceaccount-sandbox.yaml      # worker SA + sandbox-pod SA (first SA/RBAC in the chart)
├── rbac-sandbox.yaml                # Role + RoleBinding for the worker SA
├── scaledobject-sandbox.yaml        # KEDA scaler on the sandbox request queue
└── sandbox-hardening.yaml           # values-gated namespace guardrails (PSA, NetworkPolicy, quotas)

examples/sandbox/broker-kafka/       # Kafka shape (final iterations; see Examples)
examples/sandbox/broker-nats/        # NATS chart shape (final iterations; see Examples)
```

Governing rules (amendments to the #494 rules, `494-sandbox-capability/spec.md:64-94`):

1. **Coupling amendment**: `sandbox/broker/queue.py`, `queue_worker.py`, and `wire.py` may import
   `pipeline.envelope`, `pipeline.transport`, `pipeline.consumer`, `pipeline.thread_runner`, and
   `pipeline.response_store`, all of which import only `core` (verified:
   `pipeline/transport/base.py:4-6`, `pipeline/response_store/base.py:7`,
   `pipeline/consumer.py:7-9`). They must not import `pipeline.ws`, `pipeline.request_handler`,
   `pipeline.io_handler`, `pipeline.agent_runner`, `pipeline.response_handler`, `api`, or
   `deployment` (keeps fastapi/uvicorn out of the worker image). The rest of `sandbox/` keeps the
   #494 core-only rule. `docs/specs/494-sandbox-capability/spec.md`'s planned
   `deployment/aws/sandbox/` package is never created.
2. The flavor and worker modules are imported only when selected: `queue` resolves through the
   existing `_BUILTIN_BROKERS` short-name-to-dotted-path map (`sandbox/factory.py:25-28`), and
   `QueueBrokerWorker` is imported by the application's worker entry file, so `import
   agentkernel.sandbox` stays free of transport SDKs.
3. `AKConfig.get()` readers grow by exactly one module: `queue_worker.py` (its `run()` entry
   point). `queue.py` receives the `sandbox.broker` block via its constructor, exactly as
   `ThreadBroker` does (`sandbox/broker/thread.py:37-39`); transports and stores receive explicit
   constructor parameters from their factories, never config.
4. Loggers: `ak.sandbox.broker` for the client (matching `thread.py:31`),
   `ak.sandbox.broker.worker` for the worker process.
5. Public-API amendment to #494 rule 6 (`494-sandbox-capability/spec.md:84-94`):
   `agentkernel.sandbox` additionally exports `QueueBrokerWorker` (a process entry point is
   public, the `ECSAgentRunner` precedent). `QueueExecutionBroker` stays internal like every
   other concrete flavor.

### Wire contract additions and binary-safe serialization

One additive field on the completion wire model (`sandbox/broker/base.py:57-65`); it defaults
to a value that reproduces today's behavior, so the in-process flavors are untouched:

```python
class ExecutionCompletion(BaseModel):
    ...                                      # existing fields unchanged
    error_type: Optional[str] = None         # NEW: SandboxError subclass name for typed re-raise
```

- `BrokerWorkerCore.process()` (`sandbox/broker/worker.py:99-109`) stamps
  `error_type=type(exc).__name__` on its `failed`/`timed_out` completions. In-process flavors
  ignore it (they re-raise the live exception); the queue client uses it to reconstruct the typed
  error across the wire (see the client below).
- **Recovery outcome (2026-09-01).** `SandboxTask` (`sandbox/model.py`) gains
  `result_summary: Optional[dict]`: the bounded terminal outcome (stdout/stderr tails at
  `tool_output_max_chars`, `exit_code`, `error`, `notice`) that `ExecutionManager.task_status`
  captures when it consumes a terminal completion, before `broker.discard` can drop it
  (in-process flavors retain completions only until consumption). `check_sandbox_task`
  surfaces it under `"result"`; this is what makes the wait-then-check recovery contract
  deliver results, not just statuses, on every flavor.
- **Binary safety.** Pydantic v2 JSON-serializes `bytes` as UTF-8 strings, which corrupts or
  rejects arbitrary binary, and two wire spots carry binary: the `upload_file` payload
  (`payload["content"]`, set in `ExecutionManager.upload`, `sandbox/manager.py:98-100`) and
  `SandboxResult.output_files[*].content` (`SandboxFile.content: bytes`, whose docstring already
  promises "base64 over the wire", `sandbox/model.py:51-56`). Two changes:
  1. `SandboxFile` gains a `field_serializer` emitting base64 in JSON-serialization mode only,
     and a `field_validator` accepting a base64 string back into `bytes`. Python-mode dumps
     (nv_cache registry, in-process flavors) keep raw `bytes`, so stored data does not change shape.
  2. `sandbox/broker/wire.py` provides the stateless `BrokerWireCodec` class with
     `encode_request/decode_request` and
     `encode_completion/decode_completion` methods: `model_dump(mode="json")`/`model_validate` plus
     explicit base64 handling of `payload["content"]` for the `upload_file` operation (the one
     free-form binary field a JSON-mode dump cannot see). Only `queue.py` and `queue_worker.py`
     use the codec.

### The `queue` broker flavor (client): `sandbox/broker/queue.py`

```python
class QueueExecutionBroker(ExecutionBroker):
    def __init__(self, config) -> None:        # config = the sandbox.broker block (factory-injected)
        # Fail-fast validation (SandboxConfigError): config.queue block present;
        # config.response_store present. Transport and store are built lazily on first use via
        # the factory seams; the transport factory's own AKConfigError (missing backend block,
        # missing extra) propagates as-is; both fail startup loudly.
    async def submit(self, request, wait): ...  # send + bounded store poll (below)
    async def result(self, task_id): ...        # store lookup -> ExecutionCompletion | None
    # discard(): inherited no-op: durable store, TTL owns cleanup (broker/base.py:82-87)
    # close(): no-op: the send side of QueueTransport holds no consumer resources
```

Registration: `_BUILTIN_BROKERS["queue"] = "agentkernel.sandbox.broker.queue.QueueExecutionBroker"`
(`sandbox/factory.py:25-28`); no other factory change (the map already resolves short names via
`resolve_dotted`, `factory.py:195-202`).

`submit(request, wait)` semantics, in order:

1. **Effective wait.** `operation == "destroy"` → effective wait `0`: destroys are
   fire-and-forget. Ordering makes this
   safe: the destroy message shares the session's `group_id`, so per-group FIFO guarantees it is
   processed after every operation submitted before it, and `BrokerWorkerCore` destroys are
   idempotent (`worker.py:71-76`). This keeps `ExecutionManager._destroy_backend`
   (`manager.py:445-470`, which submits with `wait=None`) from blocking on a remote worker.
   Otherwise: `wait` if given, else `config.wait_timeout`: on this flavor `wait=None` is
   **bounded**, never indefinite (the "broker decides per flavor" latitude in
   `manager.py:88`); an unbounded await against a possibly-down remote worker would hang the
   agent turn, and the terminal-completion guarantee plus `task_status` recovery cover the tail.
2. **Fail-fast ceiling.** `config.worker_timeout_ceiling` set and `request.policy.timeout`
   exceeds it → `SandboxPolicyError` naming both values (design requirement; config field at
   `core/config.py:617-620`).
3. **Size guard.** Serialized request larger than `config.inline_payload_max_bytes` →
   `ExecutionBrokerError` naming the size, the limit, and the offending operation. This fires
   before the transport's own send failure because broker caps differ (SQS 256 KiB, Kafka/NATS
   about 1 MiB by default) and their errors are opaque.
4. **Send.** `QueueMessage(body=BrokerWireCodec.encode_request(request), attributes={ATTR_REQUEST_ID:
   request.task_id}, group_id=request.sandbox_session.sandbox_session_id,
   dedup_id=request.task_id)` to `QueueName.INPUT` of the sandbox transport (the
   `RequestHandler._enqueue_request` shape, `pipeline/request_handler.py:60-72`).
5. **Bounded poll.** Effective wait `0` → return a `SandboxTask(status="pending", ...)`
   immediately (the `ThreadBroker` promotion shape, `thread.py:118-128`). Otherwise poll
   `store.get_message(task_id)` every `config.wait_poll_interval` seconds (via
   `asyncio.to_thread` + `asyncio.sleep`, never `ResponseStore.get_record_with_retry`: that
   helper reads its retry config from the global `execution.response_store` block,
   which the sandbox path does not own) until the
   deadline:
   - `status == "succeeded"` → `BrokerWireCodec.decode_completion(...)`, return `completion.result`.
   - `status == "timed_out"` → raise `SandboxTimeoutError(completion.error)`.
   - `status == "failed"` → re-raise the typed error: `error_type` is looked up in
     `agentkernel.sandbox.errors` (only names defined there are honored); unknown/absent names
     raise `ExecutionBrokerError(completion.error)`. This mirrors the thread flavor's
     real-exception-while-waiting behavior (`thread.py:103-148`) as closely as the wire allows.
   - Deadline expiry → return the pending `SandboxTask`; the manager records it
     (`manager.py:249-250,273-278`) and recovery is `task_status` → `result()` (below).
   The record is read without `get_and_delete`: the store is the durable source of truth and its
   TTL cleans up (design: DB-first).

`result(task_id)`: `store.get_message(task_id)` → `BrokerWireCodec.decode_completion` or `None`. Serves
`ExecutionManager.task_status`'s fall-through (`manager.py:109-143`): the `check_sandbox_task`
recovery path, including when the task is missing from this process's registry.

### The queue broker worker: `sandbox/broker/queue_worker.py`

```python
class QueueBrokerWorker:
    @classmethod
    def run(cls) -> None:
        """Blocking worker entry point (the AgentRunner.run() analogue for sandbox execution)."""
        # 1. Read AKConfig.get().sandbox; fail fast (SandboxConfigError) unless: enabled;
        #    broker.flavor == "queue"; broker.queue block present; broker.response_store present.
        #    in_memory response store (or in_memory request transport) is allowed ONLY when the
        #    other is in_memory too (the single-process test topology); a broker transport with a
        #    non-shared store raises, mirroring ResponseStoreFactory's rule
        #    (pipeline/response_store/factory.py:34-43).
        # 2. Build: one transport over broker.queue (factory seam) serving both of the block's
        #    queues, the response store (factory seam), and
        #    BrokerWorkerCore(inline_payload_max_bytes=None)
        #    (truncation happens here in the worker, not in core).
        # 3. ThreadRunner.install_shutdown_signal_handlers(log), the IOHandler discipline
        #    (pipeline/io_handler.py:116-128): SIGTERM/SIGINT set shutdown_event and exit code 0.
        # 4. ThreadRunner.run([request-loop task, output-loop task (both exit_on_shutdown=False
        #    nested loops), sweep task (graceful=True)]), the ECSIOHandler peer-thread shape.
```

- The consumer machinery is two `ConsumerLoop`s (`pipeline/consumer.py:12-123`), the chat
  pipeline's Agent Runner / Output Consumer split applied inside one process:
  - **Request loop** on `QueueName.INPUT`: `process=cls._process_request` (async: the loop
    drives it via `asyncio.run`, `consumer.py:138-140`),
    `on_permanent_failure=cls._on_request_permanent_failure`,
    `max_receive_count=broker.queue.input.max_receive_count`,
    `num_consumers=broker.queue.input.no_of_consumers`, `batch_size=broker.queue.batch_size or 1`
    (the pipeline `AgentRunner.start` resolution), `consumer_factory=lambda:
    transport.create_consumer(QueueName.INPUT)`, `thread_name_prefix="sandbox-worker"`.
  - **Output loop** on `QueueName.OUTPUT`: `process=cls._process_completion`,
    `on_permanent_failure=cls._on_completion_permanent_failure`, the `output.*` knobs
    (`max_receive_count`, `no_of_consumers`), `thread_name_prefix="sandbox-output"`.
  - Both log to `ak.sandbox.broker.worker`.
- `_process_request(message)`, per message:
  1. `request = BrokerWireCodec.decode_request(message.body)`: a decode failure raises, so the loop nacks and
     the message retries into the permanent-failure path (no silent drop).
  2. `completion = await core.process(request)`, which never raises (`worker.py:99-109`); fail-closed
     principal/policy checks, attach-or-create self-heal, and per-session in-process locking are
     all inside `BrokerWorkerCore` and unchanged. The in-process lock is the second line; the
     transport's one-in-flight-per-group guarantee is the cross-worker line.
  3. **Truncation (v1, no offload):** `completion.result.stdout`/`.stderr` longer than
     `broker.inline_payload_max_bytes` are cut to the limit and
     `completion.result.notice` gains "output truncated at N bytes; rerun with a file
     redirection to keep full output". `output_files` whose total encoded size would push the
     record past the limit are dropped with the same notice mechanism. `result_ref` stays
     reserved and always `None` in v1 (design resolution 2026-08-24).
  4. **Send the ready-to-store record to the output queue** (shape in the next section). A send
     failure raises → nack → redelivery re-executes the operation: the same at-least-once
     semantics the chat pipeline has, stated in the docs (side-effectful commands are not
     exactly-once). Once the record is queued the at-least-once window is closed: no later
     failure re-executes the sandbox operation.
  The loop acks after `_process_request` returns (`consumer.py:144`).
- `_process_completion(message)`, per message (the `ECSOutputConsumer` role):
  1. `record = json.loads(message.body)`: a decode failure raises into the same
     nack/permanent-failure path.
  2. **DB-first store write:** `store.add_message(record)` persists the record verbatim. A
     write failure raises → nack → redelivery retries the persist only; the sandbox operation
     is never re-executed from here.
  3. **Inventory upsert** for the sweep (below), for managed profiles only, from the decoded
     completion's `sandbox_session`.
- `_on_request_permanent_failure(message)` (must catch its own exceptions, `consumer.py:48-49`):
  best-effort `BrokerWireCodec.decode_request`; on success send a `failed` completion record (`error="sandbox
  execution failed after N deliveries"`, `error_type="ExecutionBrokerError"`, the request's real
  `sandbox_session`) to the output queue; on decode failure fall back
  to `task_id = message.attributes.get(ATTR_REQUEST_ID)` and a completion with a synthesized
  placeholder `SandboxSession(sandbox_session_id=task_id or "unknown", profile="unknown",
  provider_type="unknown", created_at=now, last_used_at=now)`; with no task id at all, log at
  ERROR and return (the transport's `dead_letter` disposition still runs, `consumer.py:130-136`).
  No task with a recoverable id ends without a terminal completion.
- `_on_completion_permanent_failure(message)`: the last resort when a record could not be
  persisted within `max_receive_count` deliveries (a store outage outliving the redelivery
  budget): log at ERROR naming the `request_id` and let `dead_letter` run. The client's poll
  has long since expired into a pending `SandboxTask`, and `check_sandbox_task` keeps reporting
  it pending: the documented failure mode for a store that stays down.
- Trust boundary is unchanged from #494: providers are built worker-side by
  `SandboxProviderFactory` inside `BrokerWorkerCore` (`worker.py:62`); the agent process holds
  queue credentials only.

### Completion delivery over the output queue

Completions travel `QueueName.OUTPUT` of the same `sandbox.broker.queue` block (design
resolution 2026-08-31), mirroring the chat pipeline's Agent Runner → output queue → output
consumer shape (`ECSAgentRunner` + `ECSOutputConsumer`). The message body is the ready-to-store
record itself, so the output loop persists it verbatim:

```python
QueueMessage(
    body=json.dumps({
        "request_id": task_id,
        "session_id": request.ak_session_id,
        "status_code": <succeeded: 200, failed: 500, timed_out: 504>,
        "body": BrokerWireCodec.encode_completion(completion),
    }),
    attributes={ATTR_REQUEST_ID: task_id},
    group_id=request.sandbox_session.sandbox_session_id,
    dedup_id=task_id,                     # publish-time dedup where supported
)
```

- The queue hop is what decouples execution from store availability: once the record is
  queued, a store outage retries the persist via output-queue redelivery without re-running
  the (side-effectful) sandbox operation. The response store remains the read side: queues are
  never read by task id (`494-sandbox-capability/design.md:398-402` rejected
  receive-and-filter).
- **No agent re-invocation** (design resolution 2026-08-31): the worker never sends anything
  to the deployment's agent input queue, and no completion event exists. When the client's
  bounded poll expires, the turn ends with a pending `SandboxTask` and the
  wait-then-`check_sandbox_task` tool flow is the whole recovery contract (`task_status` →
  `result()`, above). Asynchronous resumption of a paused tool call belongs to the separate
  human-in-the-loop feature and will be designed there.

### Idle-session sweep and the response-store scan capability

- `ResponseStore` (`pipeline/response_store/base.py`) gains an optional scan capability,
  following the `supports_chunk_streaming` precedent (`base.py:53-74`):
  `supports_key_scan() -> bool` (default `False`) and
  `scan_records(prefix: str) -> list[Dict]` (default `NotImplementedError`). Implemented for
  `in_memory` (dict scan), `redis`/`valkey` (driver `SCAN` on `<prefix>*`), and `dynamodb`
  (`Scan` with `begins_with(request_id, prefix)`); a BYO store opts in by overriding both.
- Worker inventory: the output loop, after persisting each managed-profile completion (any
  terminal status: a failed operation may still have provisioned a sandbox, and a completion
  whose session no longer holds a `sandbox_id` deletes the record), upserts record
  `request_id=f"session:{sandbox_session_id}"`, `body={"provider_type", "sandbox_id", "profile",
  "idle_timeout", "last_used_at"}`. Records ride the store's TTL like completions, so a dead
  worker's records still expire (#494: `max(2 × idle_timeout, response_ttl)` is approximated by
  the single store TTL; see Config).
- Sweep task: every `broker.sweep_interval` seconds (`core/config.py:612`), when the store
  supports scanning: `scan_records("session:")`, destroy sandboxes idle past their
  `idle_timeout` via the profile's provider (`provider.destroy(sandbox_id)`), delete the
  inventory record. Attached-environment profiles are never swept (the #494 non-ownership rule,
  `sandbox/broker/worker.py:67-76`). Store without scan support: one WARNING at startup naming
  the two remaining backstops (agent-side idle reset on touch, `manager.py:366-385`, and the
  kubernetes provider's `activeDeadlineSeconds`), then the sweep task idles.
- The agent-side registry self-heals after a sweep via the existing `SandboxGoneError` path
  (`worker.py:161-186`), surfacing the recreated-empty notice.

### Factory seams (transport and response store)

- `QueueTransportFactory` (`pipeline/transport/base.py:90-201`):
  - `resolve_type(queues_config=None)` and `create(queues_config=None)`. `queues_config=None`
    reads `AKConfig.get().execution.queues` exactly as today; the default path is byte-for-byte
    unchanged, including the declared-`type`-only resolution (a queues block's `type` is
    mandatory, per the develop-side rule merged 2026-09-02) and the SQS both-URLs validation
    (the sandbox broker uses both of its block's queues, so no relaxation is needed).
  - `create_consumer(queue, queues_config=None)` threads the block through.
- `ResponseStoreFactory.create(response_store_config=None, transport_type=None, ttl=None)`
  (`pipeline/response_store/factory.py:23-75`): `None` arguments read
  `execution.response_store` / `QueueTransportFactory.resolve_type()` as today. The sandbox path
  passes `sandbox.broker.response_store`, the sandbox transport's resolved type (for the
  in_memory-pairing rule), and `ttl=sandbox.broker.response_ttl`: **the sandbox path's TTL is
  `broker.response_ttl`** (`core/config.py:611`), overriding the backend block's own `ttl`
  field, so one knob governs sandbox completion retention (design: "existing knobs reused
  as-is"). The default path ignores the new `ttl` parameter.
- The sandbox client never uses `get_record_with_retry` (its retry config is global); the
  `retry_count`/`delay` fields of the sandbox `response_store` block are
  therefore inert on this path and the config descriptions say so.

### The `kubernetes` sandbox provider: `sandbox/providers/kubernetes.py`

Reference implementation pattern: `docker.py` (sync SDK via `asyncio.to_thread`, policy mapping,
`_safe_rel` path guard, tar-based file transfer; see `providers/docker.py:33-115,160-178`).

```python
class KubernetesSandbox(Sandbox):
    # id = "<namespace>/<pod-name>" (matches the attach_to format, core/config.py:593)
    async def execute_code(self, code, language="python", timeout=None): ...   # exec: python -c
    async def execute_command(self, command, timeout=None): ...                # exec: /bin/sh -c
    async def install_packages(self, packages): ...                           # exec: pip install
    async def upload_file(self, path, content): ...    # exec "tar xf -" with a single-member tar on stdin
    async def download_file(self, path): ...           # exec "tar cf - <path>" and untar the stream
    async def close(self): ...                         # no-op: the pod keeps running for a later attach

class KubernetesSandboxProvider(SandboxProvider):
    capabilities = SandboxCapabilities(
        isolation=IsolationTier.CONTAINER, shell=True, languages=["python"], files=True,
        package_install=True, stateful=False, attach=True, provisions=True,
        attaches_external=True,            # attach_to = "<namespace>/<pod>" (mode 3)
        principal_user=False,              # flips True in the impersonation iteration
        policy_network=False,              # flips True per instance via network_policy config
        policy_filesystem=True,            # readOnlyRootFilesystem + emptyDir workdir
        policy_resources=True,             # requests/limits from policy cpu/memory_mb
    )
    def __init__(self, config, idle_timeout: int) -> None: ...   # factory passes the profile's
                                                                 # idle_timeout (the e2b/daytona
                                                                 # pattern, sandbox/factory.py:128-143)
    async def create(self, *, principal, policy) -> Sandbox: ...
    async def attach(self, sandbox_id, *, principal, policy) -> Sandbox: ...
    async def destroy(self, sandbox_id) -> None: ...
```

- **Client construction** (lazy, first use): `config.kubeconfig` set →
  `kubernetes.config.load_kube_config(config_file=...)`; else try
  `load_incluster_config()`, falling back to `load_kube_config()`. One `CoreV1Api` and one
  `NetworkingV1Api` per provider instance; every SDK call runs in `asyncio.to_thread`
  (#494 rule 3). Exec calls use `kubernetes.stream.stream(connect_get_namespaced_pod_exec, ...)`
  with `stdout/stderr` demuxed; timeouts enforced with `asyncio.wait_for` plus a best-effort
  `pkill` of the interpreter (the `docker.py:84-90` pattern).
- **`create()`** builds the pod manifest:
  - `metadata`: `name=f"ak-sandbox-{uuid4().hex[:12]}"`, `namespace=config.namespace`, labels
    `{"app.kubernetes.io/managed-by": "agent-kernel", "agentkernel.io/sandbox": "true"}` merged
    under `config.labels` (config wins on conflicts); the sweep and operators find sandbox pods
    by these labels.
  - `spec`: one container from `config.image`, `command=["sh", "-c", "sleep infinity"]`, workdir
    `/workspace`, `config.env` as env vars, `serviceAccountName=config.service_account` when
    set, `imagePullSecrets`, `nodeSelector`, `restartPolicy=Never`,
    `activeDeadlineSeconds=2 * idle_timeout` (the platform-side orphan ceiling; a session pod
    that outlives it self-heals through `SandboxGoneError` with the recreated-empty notice),
    `terminationGracePeriodSeconds=5`.
  - **securityContext defaults** (container level): `allowPrivilegeEscalation: false`,
    `seccompProfile: {type: RuntimeDefault}`, `capabilities: {drop: [ALL]}`, all safe with the
    default root-running `python:3.12-slim`. `config.security_context` (pod level) and
    `config.container_security_context` overlay on top, config winning per key; PSA-`restricted`
    namespaces additionally need a non-root image (`runAsNonRoot`), which is the hardened-image
    case and documented, not defaulted (a `runAsNonRoot` default would break the default image).
  - **Policy mapping**: `cpu`/`memory_mb` → container requests=limits; `fs_allow_read` or
    `fs_allow_write` non-empty → `readOnlyRootFilesystem: true` + an emptyDir volume at
    `/workspace` (the docker coarse mapping, `docker.py:175-177`); `network_egress`:
    - `config.network_policy: false` (default): the provider maps nothing; a non-`allow` egress
      fails closed in `BrokerWorkerCore._enforce_policy` (`worker.py:129-159`) under `strict`.
    - `config.network_policy: true`: the instance capability flips (below); `deny` creates a
      per-pod default-deny-egress NetworkPolicy selecting the pod by name label; `allowlist`
      with CIDR entries creates egress rules for those CIDRs; **domain names in
      `network_allow` are unenforceable at L3/L4** → `SandboxPolicyError` under `strict`, one
      WARNING otherwise (the `docker.py:167-170` shape). The NetworkPolicy is named after the
      pod and deleted in `destroy()`.
  - Waits for the pod to reach `Running` within a new `create_timeout` config field (default
    120 s); failure → `SandboxProvisionError` with the pod's last condition message, and the pod
    is deleted (no orphan from a failed create).
- **Instance capability override** (the design's new pattern, defined once here): a provider
  whose enforcement depends on operator-asserted infrastructure may override `capabilities` per
  instance in `__init__` via `self.capabilities = type(self).capabilities.model_copy(update=...)`.
  Consumers already read `provider.capabilities` on the instance (`worker.py:121,134`;
  `factory.py:77`), so instance attribute shadowing is sufficient. `network_policy: true` is v1's
  only use: `policy_network=True` asserts the cluster CNI enforces NetworkPolicy, which the
  provider cannot detect.
- **`attach(sandbox_id)`**: parse `"<namespace>/<pod>"` (a bare pod name uses
  `config.namespace`); `read_namespaced_pod` 404, or phase in `Succeeded`/`Failed`, or a
  deletion timestamp → `SandboxGoneError`; phase `Pending` → the same bounded wait as create.
- **`destroy(sandbox_id)`**: delete the pod and its NetworkPolicy if one exists; 404s are
  no-ops (idempotent).
- **Factory branch** (`sandbox/factory.py:_build`): `require_extra("kubernetes", "sandbox
  provider 'kubernetes'")`, constructed as
  `KubernetesSandboxProvider(config_block, idle_timeout=profile.idle_timeout)`; `"kubernetes"`
  appended to `_BUILTIN_PROVIDER_NAMES` (`factory.py:20`).
- **Security-boundary documentation** (shipped with the provider docs): restricted execution is
  enforced by the credential: bind the sandbox pod's ServiceAccount to a read-only
  (Cluster)Role and the API server rejects writes regardless of the command string. Command
  parsing is never a boundary (#587 documents the injection gap this rule exists to prevent).

### RBAC impersonation (iteration 8)

- `SandboxPrincipal.credentials` carries `{"user": <name>, "groups": [<g>...]}` (the
  `principal.py` resolver contract; the `ec2_ssm` provider's `role_arn`/`run_as` precedent,
  `providers/ec2_ssm.py:11-15`); `user` falls back to the principal's `subject` and `groups`
  to the principal's first-class `groups` list.
- Under a `user`-mode principal, `_apis_for(principal)` builds a per-`(user, groups)` API
  client pair whose default headers carry `Impersonate-User` and `Impersonate-Group`, so the
  API server enforces the invoking user's own RBAC on pod create/read, exec, and
  NetworkPolicy creation. Clients are cached per subject (the `ec2_ssm` per-subject cache
  pattern, `ec2_ssm.py:171-174`); the sandbox handle keeps the impersonated client, so exec
  stays under the user for the handle's lifetime.
- Two fail-closed limits (resolution 2026-09-02): a user-mode principal with no resolvable
  user rejects with `SandboxPolicyError`, and **at most one group** is supported: the Python
  client's plain-dict default headers cannot repeat `Impersonate-Group`, so multiple groups
  reject with an actionable error (bind RBAC to the user or a single group) instead of
  silently dropping groups.
- **Disposal stays under the worker's own identity** (resolution 2026-09-02, amending the
  every-call wording): the `destroy` ABC carries no principal, and the idle sweep destroys
  with no user in context; disposal is platform-owned, exactly like the sweep.
- `capabilities.principal_user` flips to `True`; the worker's existing fail-closed check
  (`worker.py:113-127`) starts admitting `identity.mode: user` profiles on this provider with
  no worker change.
- The chart gains the worker-side prerequisite the original sketch missed: honoring
  `Impersonate-*` headers requires the caller to hold the cluster-scoped `impersonate` verb
  on `users`/`groups`, so `rbac-sandbox.yaml` renders a ClusterRole + ClusterRoleBinding
  (the chart's first and only ClusterRole) gated behind `sandboxWorker.rbac.impersonate`
  (default false).

### Consumer changes

- `sandbox/factory.py`: `_BUILTIN_BROKERS` + `"queue"`; `_BUILTIN_PROVIDER_NAMES` +
  `"kubernetes"`; one new provider `if/elif` branch. Nothing else changes.
- `sandbox/broker/worker.py`: `process()` stamps `error_type` (one line per except arm). `run()`
  unchanged.
- `sandbox/model.py`: `SandboxFile` (de)serializers and the additive
  `SandboxTask.result_summary`. All other models unchanged.
- `sandbox/manager.py`: `task_status` stamps `result_summary` at the terminal transition (a
  new `_summarize_completion` helper); `sandbox/tools.py`: `check_sandbox_task` returns it
  under `"result"` and the system-prompt guidance says so. Nothing else in either file
  changes.
- `sandbox/__init__.py`: `+ QueueBrokerWorker` in imports and `__all__`.
- `pipeline/transport/base.py` and `pipeline/response_store/factory.py`: the optional-parameter
  seams; every existing caller passes nothing and resolves identically (verified call sites:
  `agent_runner.py:32`, `request_handler.py`, `io_handler.py`, `response_handler.py`,
  `ws/handler.py`, ECS handlers via the shims).
- `pipeline/response_store/{base,in_memory,redis,valkey,dynamodb}.py`: the optional scan
  capability; `redis.py`/`valkey.py`/`dynamodb.py` also accept the constructor `ttl` they
  already take (no signature change, the factory just passes the sandbox value).
- **Verified unchanged**: `ExecutionManager` beyond the `result_summary` capture (the flavor
  absorbs all queue semantics), `SandboxPreHook`, the tools other than `check_sandbox_task`,
  `EmbeddedBroker`/`ThreadBroker`, `BrokerWorkerCore`
  logic other than `error_type`, `ConsumerLoop`, `ThreadRunner`, all chat-pipeline components,
  all deployment adapters, `core/model.py`, `core/chat_service.py`.

### Config changes

`_ExecutionBrokerConfig` (`core/config.py:602-624`):

```python
class _ExecutionBrokerConfig(BaseModel):
    flavor: str = Field(default="thread", description="Broker flavor: 'embedded' | 'thread' (in-process) | 'queue' (transport-backed, #503) | a dotted path to an ExecutionBroker subclass")
    wait_timeout: float = ...                 # unchanged (607); also the queue flavor's wait=None bound
    wait_poll_interval: float = Field(default=0.5, description="Seconds between response-store polls while a queue-flavor caller waits synchronously")   # NEW
    inline_payload_max_bytes: int = ...       # unchanged (608-610); request reject + result truncation limit
    response_ttl: int = ...                   # unchanged (611); TTL for sandbox completion and inventory records
    sweep_interval: int = ...                 # unchanged (612)
    worker_timeout_ceiling: Optional[float] = ...   # unchanged (617-620)
    queue: Optional[_QueuesConfig] = Field(default=None, description="Sandbox broker queues for the 'queue' flavor; reuses the execution.queues shape (input carries execution requests to the worker, output carries completions back to the response store)")   # NEW
    response_store: Optional[_ResponseStoreConfig] = ...   # unchanged (621-624); required by the 'queue' flavor
    # REMOVED: request_queue_url (613), object_store_bucket (614-616)
```

- **Removals**: `request_queue_url` and `object_store_bucket` have zero readers in `ak-py/src`
  and `ak-py/tests` (verified by exhaustive grep; the only hits are the field definitions).
  `_ExecutionBrokerConfig` is a plain `BaseModel` (pydantic v2 default `extra="ignore"`), so
  values still present in YAML or as `AK_SANDBOX__BROKER__*` env vars are ignored after
  removal: no startup failure, verified by a test.
- Reusing `_QueuesConfig` (`core/config.py:475-499`) verbatim gives every transport's sub-block
  and documentation for free: `AK_SANDBOX__BROKER__QUEUE__TYPE`,
  `AK_SANDBOX__BROKER__QUEUE__NATS__URL`, `AK_SANDBOX__BROKER__QUEUE__INPUT__NO_OF_CONSUMERS`,
  etc. Semantics notes added to the sandbox docs: `input.*` drives the request loop;
  `output.*` drives the output loop; NATS `ack_wait` must exceed the largest profile `policy.timeout`
  (the redelivery trap the field description already warns about for agent turns).
- `_SandboxKubernetesConfig` (`core/config.py:590-595`) grows (existing four fields unchanged):

```python
    service_account: Optional[str] = Field(default=None, description="ServiceAccount assigned to sandbox pods; bind it to the (read-only) RBAC role that is the execution's security boundary")
    image_pull_secrets: list[str] = Field(default_factory=list, description="imagePullSecrets names for the sandbox pod")
    labels: dict[str, str] = Field(default_factory=dict, description="Extra labels merged onto sandbox pods")
    node_selector: dict[str, str] = Field(default_factory=dict, description="nodeSelector for sandbox pods")
    env: dict[str, str] = Field(default_factory=dict, description="Environment variables set in the sandbox container")
    security_context: dict[str, Any] = Field(default_factory=dict, description="Pod-level securityContext overlay")
    container_security_context: dict[str, Any] = Field(default_factory=dict, description="Container-level securityContext overlay (over the hardened defaults)")
    network_policy: bool = Field(default=False, description="Create per-pod NetworkPolicies for deny/allowlist egress and declare policy_network; set only when the cluster CNI enforces NetworkPolicy")
    create_timeout: float = Field(default=120.0, description="Seconds to wait for a sandbox pod to reach Running before failing provisioning")
```

- `ak-py/pyproject.toml`: `kubernetes = ["kubernetes>=29.0.0"]` extra (the #494 note that the
  kubernetes extra lands with its provider, `494-sandbox-capability/spec.md:644-646`).
- Compatibility: all additions are optional with defaults; YAML and env vars written before this
  change behave identically except the two removed (ignored) fields. Field descriptions are
  present on every new field (they surface in generated docs).

### Helm chart changes (`ak-deployment/ak-k8s/chart/`)

Values (new top-level `sandboxWorker` block, default `enabled: false`, so all rendered
manifests are unchanged unless enabled (the `wsGateway` precedent, `values.yaml:162-163`):

```yaml
sandboxWorker:
  enabled: false
  replicaCount: 1
  image: {}                                   # falls back to top-level image (agent-kernel.image helper)
  command: ["python", "app_sandbox_worker.py"]
  resources: {}
  extraEnv: []
  podAnnotations: {}
  nodeSelector: {}
  tolerations: []
  affinity: {}
  terminationGracePeriodSeconds: 600          # drain must outlive the longest policy.timeout
  preStopSleepSeconds: 5
  serviceAccount:
    create: true                              # the chart's first ServiceAccount objects
    name: ""                                  # default: <fullname>-sandbox-worker
  rbac:
    create: true                              # Role + RoleBinding in the sandbox namespace
    networkPolicies: false                    # add networkpolicies create/delete to the Role
                                              #   (needed only with kubernetes.network_policy: true)
    impersonate: false                        # ClusterRole granting the impersonate verb
                                              #   (needed only for identity.mode: user profiles)
  sandboxPods:
    namespace: ""                             # default: the release namespace
    serviceAccount:
      create: true                            # <fullname>-sandbox-pod; the app config points
      name: ""                                #   kubernetes.service_account at it
  queue:                                      # sandbox queue names per transport (input + output)
    nats:
      inputStream: SANDBOX_REQUESTS
      inputSubjectPrefix: sandbox.req
      outputStream: SANDBOX_COMPLETIONS
      outputSubjectPrefix: sandbox.done
      partitions: 32
    kafka: {inputTopic: sandbox-input, outputTopic: sandbox-output}
    sqs: {inputUrl: "", outputUrl: ""}
  hardening:
    enabled: false
    podSecurityStandard: restricted           # PSA labels on the sandbox namespace
    defaultDenyEgress: true
    egressAllow: []                           # CIDR peers (e.g. the API server) + port entries
    resourceQuota: {}                         # rendered verbatim when set
    limitRange: {}
```

Templates, following the surveyed patterns exactly:

- `deployment-sandbox-worker.yaml`: gate `{{- if .Values.sandboxWorker.enabled }}`; the
  `deployment-agent-runner.yaml` shape verbatim (labels/selector helpers with
  `component "sandbox-worker"`, `checksum/env` annotation, `envFrom` the shared `-env`
  ConfigMap, command/resources/preStop/nodeSelector blocks; see `deployment-agent-runner.yaml:1-79`)
  plus `serviceAccountName` (the first tier to set one).
- `serviceaccount-sandbox.yaml` / `rbac-sandbox.yaml`: worker SA; Role in the sandbox-pods
  namespace with `pods` (`create/get/list/watch/delete`), `pods/exec` (`create` AND `get`:
  the Python client's WebSocket exec is a GET, and with only the SPDY verb `create` every
  exec fails its handshake with a 403, which kubernetes-client masks as an
  `AttributeError`; the provider re-raises that case with the RBAC hint), and, when the
  app config uses `network_policy: true`, `networkpolicies` (`create/delete`), gated by a
  `sandboxWorker.rbac.networkPolicies` flag; RoleBinding worker-SA → Role; the sandbox-pod SA
  (deliberately bound to nothing: the application example binds it to `view` or a custom role,
  because what sandbox pods may do is application policy, not chart policy).
- `scaledobject-sandbox.yaml`: gate `{{- if and .Values.keda.enabled
  .Values.sandboxWorker.enabled }}` (the `scaledobject.yaml:1` shape); triggers mirror the
  existing three branches (`scaledobject.yaml:21-42`) with the sandbox queue names: kafka
  consumer group `{{ printf "%s-input" .Values.transport.kafka.groupId }}` is replaced by the
  sandbox group, topic `sandboxWorker.queue.kafka.inputTopic`; nats-jetstream on
  `sandboxWorker.queue.nats.inputStream`; aws-sqs-queue on `sandboxWorker.queue.sqs.inputUrl`
  (scaling keys on the input backlog; the output queue drains at store speed).
- `sandbox-hardening.yaml`: gate `{{- if and .Values.sandboxWorker.enabled
  .Values.sandboxWorker.hardening.enabled }}`; renders PSA labels
  (`pod-security.kubernetes.io/enforce: <standard>`), as a Namespace patch when
  `sandboxPods.namespace` names a chart-created namespace, otherwise documented as an operator
  step (labeling a pre-existing release namespace from a chart is not reliably possible);
  default-deny-egress NetworkPolicy selecting `agentkernel.io/sandbox: "true"` pods with
  `egressAllow` peers appended; ResourceQuota/LimitRange rendered verbatim when set.
- `configmap-env.yaml` gains a `{{- if .Values.sandboxWorker.enabled }}` block emitting, with
  the existing per-transport `if eq .Values.transport.type` branching (`configmap-env.yaml`
  pattern at lines 24-43): `AK_SANDBOX__BROKER__FLAVOR: "queue"`,
  `AK_SANDBOX__BROKER__QUEUE__TYPE: {{ .Values.transport.type }}`, the sandbox input and
  output queue names
  (`AK_SANDBOX__BROKER__QUEUE__NATS__*` / `__KAFKA__*` / `__INPUT__URL` / `__OUTPUT__URL`),
  broker URLs reusing
  the `agent-kernel.natsUrl`/`agent-kernel.kafkaBootstrap` helpers, and
  `AK_SANDBOX__BROKER__RESPONSE_STORE__*` from the existing `responseStore` values block.
  Everything else about the sandbox capability (profiles,
  policies, provider config) lives in the application image's `config.yaml`, per the chart's
  application-image contract.
- **Standalone install** (the Kafka/Lambda shape's cluster half, resolution 2026-09-01): the
  sandbox worker must deploy without the rest of the pipeline, so `ioHandler` gains an
  `enabled` flag (default `true`; `deployment-io.yaml`, `service.yaml`'s io Service, the io
  HPA, and the NOTES API section gate on it), and `configmap-env.yaml` emits the chat
  pipeline's `AK_EXECUTION__QUEUES__*` / `AK_EXECUTION__RESPONSE_STORE__*` values only when
  some pipeline tier (`ioHandler`/`agentRunner`/`wsGateway`) is enabled, so an SQS
  worker-only install never has to invent chat queue URLs. With all pipeline tiers disabled,
  the release carries only the sandbox worker plus the shared sandbox queues and response
  store the out-of-cluster agent side (Lambda, ECS) also points at; the README documents the
  values and the agent-side mirror configuration.
- CI: `chart-test.yaml`'s explicit-render step gains two renders:
  `--set sandboxWorker.enabled=true --set sandboxWorker.hardening.enabled=true` (the lint-only
  gate for optional tiers, `chart-test.yaml:65-80`) and a standalone worker-only render
  (io/runner disabled, external Kafka + Redis); the kind smoke matrix is unchanged (the
  broker-nats example is the e2e vehicle).

### Examples (final iterations)

Both follow the surveyed house patterns; exact prompts/sentinels are implementation detail, the
required coverage is normative.

- **`examples/sandbox/broker-kafka/`** (the Kafka shape, modeling #587's topology): the
  transport-example layout (`README.md`, `app.py` with an `ENTRYPOINTS = {"app": ..., "worker":
  QueueBrokerWorker.run}` dispatch, `config.yaml`, `docker-compose.yaml` with the
  `apache/kafka` + `valkey` services and healthchecks copied from `examples/transport/kafka`,
  `k8s/rbac.yaml`, `build.sh`, `app_test.py`, `pyproject.toml`, `test-config.yaml`). The agent
  process runs the CLI with `broker.flavor: queue` over Kafka and a valkey response store; the
  worker process consumes and drives a `kubernetes` profile against a kind cluster whose
  `k8s/rbac.yaml` binds the sandbox-pod ServiceAccount to the `view` ClusterRole; the sandbox
  image is `alpine/k8s` (in-cluster SA credentials; the bitnami catalog restructuring removed the kubectl tags). `app_test.py` (self-skipping when
  `docker`/`kind`/`OPENAI_API_KEY` are unavailable, the `examples/transport/kafka/app_test.py:58-64`
  pattern) covers: a read-only kubectl command returning within the bounded poll; a write
  command rejected by RBAC (Forbidden), asserted with a sentinel; and a promoted long execution
  recovered via `check_sandbox_task`. The Lambda-mode variant (sandbox queues on Kafka, DynamoDB
  response store) is a README section, not automated. Registered in
  `.github/test-config.yaml` as `type: containerized` (behaviorally identical to `cli`;
  `run_single_test.py` runs `./build.sh local` + pytest either way).
- **`examples/sandbox/broker-nats/`** (the NATS chart shape): builds on
  `examples/k8s/openai-queue-mode`, adding `app_sandbox_worker.py`
  (`QueueBrokerWorker.run()` behind a `main()`), `deploy/Dockerfile.sandbox-worker`, a
  `config.nats.yaml` sandbox block (kubernetes profile, hardened image reference,
  `security_context`, `service_account`), and a chart values overlay enabling `sandboxWorker`
  and `sandboxWorker.hardening`. The README demonstrates the promotion recovery end to end:
  submit a long-running task, watch the turn end with a pending task, and fetch the finished
  result with `check_sandbox_task` on the next turn. Registered in `.github/test-config.yaml`
  as `type: containerized` (resolution 2026-09-01, superseding the walkthrough-only choice):
  its `app_test.py` builds the images, installs the chart on a kind cluster with the values
  overlay, and drives the walkthrough as deterministic curl sentinels, self-skipping when
  docker/kind/kubectl/helm or the OpenAI key is unavailable.

### Behavioural changes

All intentional; none reachable unless `sandbox.enabled: true` except 5-8:

1. `ExecutionBrokerFactory` accepts `flavor: queue` (previously `SandboxConfigError`, asserted
   by `test_sandbox_broker.py:356-361`; that test's expectation list gains `queue`).
2. `request_queue_url` and `object_store_bucket` are removed from `_ExecutionBrokerConfig`;
   stale YAML/env values are silently ignored (pydantic `extra="ignore"`), verified by test.
3. `ExecutionCompletion` gains `error_type` (default `None`); `BrokerWorkerCore.process`
   stamps `error_type` on failure completions. Wire-additive; in-process flavors behave
   identically.
4. `SandboxFile.content` serializes as base64 in JSON mode and validates base64 strings back to
   bytes. No in-repo consumer JSON-dumps these models today (the nv_cache registry uses
   python-mode dumps), so no stored data changes shape.
5. `QueueTransportFactory.resolve_type`/`create`/`create_consumer` gain an optional
   `queues_config` parameter; omitted, resolution is byte-for-byte today's.
6. `ResponseStoreFactory.create` gains optional `response_store_config`/`transport_type`/`ttl`
   parameters; omitted, resolution is byte-for-byte today's.
7. `ResponseStore` gains the optional scan capability (`supports_key_scan`, `scan_records`);
   base defaults are `False`/`NotImplementedError`, so BYO stores are unaffected until they opt
   in.
8. The ak-k8s chart gains the `sandboxWorker` values block and five templates, all inert at
   default values; the chart acquires its first ServiceAccount/RBAC objects (only when enabled).
9. `kubernetes` becomes a resolvable built-in provider (previously "unknown sandbox provider
   type"); `_SandboxKubernetesConfig` gains nine fields.
10. On the `queue` flavor only: `wait=None` is bounded by `wait_timeout` (in-process flavors
    keep indefinite waits), and `destroy` submissions are fire-and-forget.
11. The instance-level capability override pattern is introduced (one use:
    `network_policy: true` flips `policy_network` on the provider instance).
12. `agentkernel.sandbox` exports `QueueBrokerWorker`.
13. `check_sandbox_task` on finished tasks includes the bounded outcome under `"result"`, and
    `task_status` persists it into the session registry (`SandboxTask.result_summary`,
    additive: registry entries written before this change read back with it unset). Applies
    to every flavor, not just `queue`.

**Non-changes**: `EmbeddedBroker`/`ThreadBroker` behavior; `ExecutionManager`, `SandboxPreHook`,
tools, principal resolution; `BrokerWorkerCore`'s fail-closed checks, self-heal, per-session
locking, and log messages; the `execution.*` config section and every chat-pipeline component;
session/nv_cache data layouts;
all existing public exports; all existing transports' wire formats.

## Error handling

- **Startup (fail-fast, before any message flows)**: missing `broker.queue` or
  `broker.response_store` on the `queue` flavor → `SandboxConfigError` naming the block
  (client constructor and `QueueBrokerWorker.run`); a broker transport paired with an in_memory
  (or absent) response store → `SandboxConfigError` (the `ResponseStoreFactory` rule restated
  sandbox-side); missing transport backend block or extra → the transport factory's existing
  `AKConfigError`/`ImportError` propagate; unknown flavor → the existing `SandboxConfigError`
  listing built-ins (`sandbox/factory.py:195-199`).
- **Client submit**: ceiling exceeded → `SandboxPolicyError`; oversized request →
  `ExecutionBrokerError`; transport send failure → the transport's exception propagates (the
  tool layer converts every `SandboxError` and unexpected exception to `{"error": ...}` JSON,
  the #494 surfacing rule).
- **Client wait**: `failed` completion → typed re-raise via `error_type` (names resolved only
  from `agentkernel.sandbox.errors`; anything else → `ExecutionBrokerError` with the completion's
  `error` text); `timed_out` → `SandboxTimeoutError`; deadline expiry → `SandboxTask` (not an
  error); store read exceptions during polling → logged at WARNING, poll continues until
  deadline (a transiently unavailable store must not fail an execution that is still running).
- **Worker, request loop**: request decode failure → raise → nack → bounded redelivery →
  permanent-failure completion + `dead_letter` (no silent black hole); provider/machinery
  failures never escape `BrokerWorkerCore.process`; output-queue send failure → raise → nack →
  redelivery re-executes (documented at-least-once semantics; the window closes once the
  record is queued); both permanent-failure hooks catch everything themselves (the
  `ConsumerLoop` contract, `pipeline/consumer.py:48-49`).
- **Worker, output loop**: record decode failure or store write failure → raise → nack →
  redelivery retries the persist only (the sandbox operation never re-runs from here);
  persistence still failing after `max_receive_count` deliveries → ERROR log naming the
  `request_id` + `dead_letter`, and the task stays pending from the client's perspective.
- **Kubernetes provider**: pod create/wait failure → `SandboxProvisionError` (pod deleted, no
  orphan); gone/terminated attach target → `SandboxGoneError`; domain entries in an enforced
  allowlist → `SandboxPolicyError` under `strict`, WARNING otherwise; exec timeout →
  `SandboxTimeoutError` after best-effort kill; missing SDK →
  `pip install "agentkernel[kubernetes]"` via `require_extra`.

## Testing

New file `ak-py/tests/test_sandbox_queue_broker.py`, reusing the established scaffolding: the
`reset_singletons` autouse fixture shape (`test_sandbox_broker.py:46-59`: `AKConfig._reset`,
`ExecutionManager._reset`, `SandboxProviderFactory._reset`, `Runtime._system_*_hooks = None`)
plus `InMemoryTransport.reset()` (`test_transport_contract.py:12-16`), the `_install_cfg`
config-stub pattern (`test_sandbox_broker.py:62-70`), the `FakeSandboxProvider` dotted type
(`test_sandbox.py:82`), and direct `worker._process(message)` calls for single-message cases
with a short-lived real consumer thread for the end-to-end case. All over the `in_memory`
transport and `InMemoryResponseStore` (the permitted single-process pairing); no live broker.

Asserts:

- **Round trip**: submit → worker consume → DB-first record (status_code 200) → poll returns the
  `SandboxResult`; binary fidelity through `wire.py` for `upload_file` payloads and
  `output_files` (non-UTF-8 bytes).
- **Wait semantics**: `wait=0` promotes immediately; deadline expiry promotes and the late
  completion is recovered via `task_status` → `result()`; `wait=None` is bounded by
  `wait_timeout`; `destroy` is fire-and-forget and orders after a prior
  operation in the same group (FIFO assertion).
- **Typed errors**: `failed` completion with `error_type: SandboxPolicyError` re-raises
  `SandboxPolicyError`; unknown `error_type` → `ExecutionBrokerError`; `timed_out` →
  `SandboxTimeoutError`.
- **Output-queue delivery**: the request loop sends the ready-to-store record to
  `QueueName.OUTPUT` with the specified body, attributes, `group_id=sandbox_session_id`,
  `dedup_id=task_id`; the output loop persists it verbatim (`store.get_record` sees the
  `status_code` and the encoded completion); a store write failure nacks and the redelivered
  output message persists on retry without the sandbox operation running again (FakeSandbox
  call-count assertion).
- **End-to-end promotion recovery**: a deadline expiry promotes to a pending `SandboxTask`;
  after both worker loops run, `task_status` → `result()` (the `check_sandbox_task` path)
  returns the terminal completion from the store, and the manager-level test asserts the
  bounded outcome reaches `check_sandbox_task`'s `"result"` (with the thread flavor's
  late-completion test asserting the same on an in-process flavor).
- **Permanent failure**: after `max_receive_count` request deliveries a `failed` completion
  with the request's real `sandbox_session` reaches the store via the output queue and the
  request message is dead-lettered; the undecodable-body fallback writes the
  placeholder-session completion keyed by the `ATTR_REQUEST_ID` attribute; an output record
  that cannot be persisted within its own `max_receive_count` logs the ERROR and dead-letters.
- **Truncation**: oversized stdout is cut with the notice; oversized request rejected at submit.
- **Sweep**: with a scan-capable fake store, an idle inventory record triggers
  `provider.destroy` and record deletion; attached profiles untouched; scan-less store logs the
  WARNING and idles.
- **Fail-fasts**: each startup validation raises the named error; ceiling rejection.
- **Existing file updates**: `test_sandbox_broker.py:356-361`'s built-in list gains `queue`;
  a new config test asserts stale `request_queue_url`/`object_store_bucket` YAML keys and env
  vars are ignored. No existing patch targets move.

`ak-py/tests/test_sandbox_providers.py` additions (the `docker_env` fake-SDK pattern,
`test_sandbox_providers.py:246-254`: `monkeypatch.setitem(sys.modules, "kubernetes", fake)` plus
module rebind):

- `TestKubernetesContract(SandboxProviderContract)` with a `provider` fixture over the fake SDK
  (the `TestLocalSubprocessContract` shape, `test_sandbox_providers.py:58-63`).
- Provider specifics: pod manifest assertions (name prefix, managed-by labels, SA,
  merged securityContext with hardened defaults, requests=limits, `activeDeadlineSeconds`,
  `restartPolicy`, emptyDir-on-filesystem-policy); `to_thread` usage; exec argv shapes; tar
  round trip; attach parsing (`ns/pod` and bare name), 404/terminated → `SandboxGoneError`;
  destroy idempotence incl. NetworkPolicy cleanup; `network_policy: true` flipping the instance
  capability while the class default stays `False`; allowlist-with-domains failing under
  `strict`; create-timeout → `SandboxProvisionError` with pod cleanup.

`ak-py/tests/test_sandbox.py`: factory tests for the `kubernetes` branch (resolution, missing
config block, missing extra message naming `agentkernel[kubernetes]`).

`ak-py/tests/test_response_store_in_memory.py` (or a sibling): the scan capability on the
in-memory store; redis/valkey/dynamodb scan methods tested with mocked drivers in their existing
files' style.

Run: `cd ak-py && uv run pytest` (per-file:
`uv run pytest tests/test_sandbox_queue_broker.py tests/test_sandbox_providers.py -x`).

## Documentation

- `docs/docs/advanced/sandbox.md`: the `queue` flavor section (topology diagrams for both
  shapes, the wait-then-`check_sandbox_task` recovery contract, at-least-once semantics,
  sizing `ack_wait`/visibility against
  `policy.timeout`), the kubernetes provider row (isolation tier `container`, extra
  `kubernetes`), and the RBAC-not-string-parsing security guidance.
- `docs/docs/advanced/queue-mode-guide.md`: a cross-reference note that the sandbox broker rides
  the same transports with its own queue config.
- `ak-py/README.md`: the `kubernetes` extra. `ak-deployment/ak-k8s/README.md`: the
  `sandboxWorker` tier and hardening values.
- Dev-skill sync at merge (plan.md's final iteration): `ak-dev-architecture` (sandbox section:
  flavors, worker, coupling amendment), `ak-dev-new-sandbox-provider` (provider table + the
  instance-capability-override pattern), `ak-dev-new-queue-transport` (a note that transports
  are also consumed by the sandbox broker via the factory seam).
