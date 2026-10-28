# #641: Split `execution.mode` into an invocation mode and a reply `message_type` — Implementation Spec

This spec details how [`design.md`](design.md) is built. One new enum (`ReplyMessageType`) and one
new config field (`execution.message_type`) sit next to `ExecutionMode`. `_ExecutionConfig`
validates the pair once, at config load, and exposes four read-only predicates. Every call site
that compares `mode` to `STREAM` today asks one of those predicates instead. `ExecutionMode.STREAM`
is deleted, and a config that still sets it fails at load with a two-line migration message.

- Paths are relative to `ak-py/src/agentkernel/` unless they start with `ak-py/`, `ak-deployment/`,
  `examples/`, `docs/` or `.github/`.
- Line numbers are from `develop` at `fec2b144`.

## Design

### §1 `ReplyMessageType` and `ExecutionMode` (`core/model.py`)

```python
class ExecutionMode(str, Enum):
    """How a request is invoked, which also fixes the transport its reply travels on.

    - REST_SYNC / REST_ASYNC: over REST (JSON reply, submit + poll, or SSE for delta replies).
    - ASYNC: over WebSocket only.
    - REALTIME: a persistent model socket (voice) through an integration gateway.
    How much of the reply each message carries is execution.message_type (ReplyMessageType).
    """

    REST_SYNC = "rest_sync"
    REST_ASYNC = "rest_async"
    ASYNC = "async"
    REALTIME = "realtime"


class ReplyMessageType(str, Enum):
    """How much of the reply each delivered message carries (execution.message_type)."""

    COMPLETE = "complete"  # one message with the whole reply
    DELTA = "delta"        # one message per StreamChunk, ending with the done chunk
```

- `STREAM = "stream"` (`core/model.py:330`) is deleted. The docstring (`:315-325`) is rewritten as above.
- `ReplyMessageType` is not named `MessageType`: `pipeline/response_handler.py` also imports
  `WebSocketHandlerABC`, whose nested `MessageType` (`pipeline/ws/base.py:68`) it uses by that name.
- `core/config.py:7` imports both enums from `.model`, so `from agentkernel.core.config import
  ExecutionMode, ReplyMessageType` works the way the existing `ExecutionMode` import does
  (`deployment/aws/serverless/aklambda.py:7`). Neither enum is exported from a package `__init__`, today or after.

### §2 `_ExecutionConfig` (`core/config.py:690`)

```python
class _ExecutionConfig(BaseModel):
    STREAM_MIGRATION_MESSAGE: ClassVar[str] = (
        "execution.mode 'stream' was removed. For SSE over REST set execution.mode: rest_sync and "
        "execution.message_type: delta; for chunks over WebSocket set execution.mode: async and "
        "execution.message_type: delta (env: AK_EXECUTION__MODE, AK_EXECUTION__MESSAGE_TYPE)"
    )

    mode: Optional[ExecutionMode] = Field(default=None, description=...)            # stream dropped
    message_type: Optional[ReplyMessageType] = Field(default=None, description=...)  # new
    queues: ...            # unchanged
    response_store: ...    # unchanged
    realtime: ...          # unchanged

    @model_validator(mode="before")
    @classmethod
    def _reject_legacy_stream(cls, data: Any) -> Any: ...   # mode == "stream" -> AKConfigError(STREAM_MIGRATION_MESSAGE)

    @model_validator(mode="after")
    def _check_message_type(self) -> "_ExecutionConfig": ...  # matrix below -> AKConfigError

    @property
    def resolved_message_type(self) -> ReplyMessageType: ...  # message_type, else DELTA for realtime, else COMPLETE

    @property
    def is_websocket(self) -> bool: ...  # mode == ASYNC

    @property
    def is_delta(self) -> bool: ...      # resolved_message_type == DELTA and mode != REALTIME (False for realtime)

    @property
    def is_sse(self) -> bool: ...        # is_delta and not is_websocket (rest_sync or unset mode, delta)
```

Field descriptions (they surface in generated docs):

- `mode`: "Invocation mode: rest_sync (REST, wait for the reply), rest_async (REST, submit then
  poll), async (WebSocket only), realtime (persistent realtime sockets, e.g. the LiveKit voice
  gateway). Unset runs as rest_sync."
- `message_type`: "Reply delivery: complete (one message with the whole reply) or delta (one
  message per chunk: SSE under rest_sync, WebSocket chunks under async). Unset resolves to delta
  for realtime and complete otherwise."

Rules:

1. **The predicates are the only place `mode` and `message_type` are combined.** No call site
   reads `message_type` or compares `mode` to `ASYNC` to mean "WebSocket". Comparisons that mean
   a specific mode stay as they are: `REST_SYNC`/`REST_ASYNC` route dispatch, and `REALTIME`
   runner and route selection.
2. **`is_delta` excludes `realtime`.** `realtime` always resolves to `delta` but has its own runner
   (`RealtimeAgentRunner`) and delivery (`ResponseHandler._deliver_realtime`). Every site that
   selects the token-streaming runner or chunk delivery reads `is_delta`, so a voice turn never
   reaches `StreamAgentRunner`. The property's docstring says so, because `resolved_message_type`
   is `DELTA` for `realtime` while `is_delta` is false.
3. **`is_sse` is defined by exclusion.** Load-time validation leaves `rest_sync` (or unset) as the
   only non-WebSocket mode that can be `delta`, so `is_delta and not is_websocket` means exactly
   "SSE over REST".
4. **Load-time checks are config-only.** `_check_message_type` rejects the two ❌ cells of the design
   matrix and nothing else. Rules that depend on the transport, the response store or the host
   (broker without a chunk store, ECS, Lambda, webhooks) run at startup, in the entry point that
   owns them (§3, §5, §6).
5. **Prose follows the code.** Docstrings, comments and error text that call `STREAM` a mode name
   the pair instead (about 40 lines in `pipeline/` and `deployment/aws/`, from `grep -rnw STREAM src`).
   Log tags such as `[STREAM AGENT START]` and `[STREAM REQUEST]` stay, so existing log queries keep
   matching.

`_check_message_type` (it runs only when `message_type` is set, since the default always resolves to a valid cell):

| `mode` | `message_type` | Error |
| --- | --- | --- |
| `rest_async` | `delta` | "execution.mode rest_async with execution.message_type delta is not supported: polling returns one stored reply. Use message_type complete, or mode rest_sync (SSE) or async (WebSocket) with delta" |
| `realtime` | `complete` | "execution.mode realtime with execution.message_type complete is not supported: realtime always streams. Leave message_type unset or set it to delta" |

`_reject_legacy_stream`:

- It runs before field parsing, so the user sees the migration message, not Pydantic's "Input
  should be 'rest_sync', 'rest_async', 'async' or 'realtime'".
- It acts only when `data` is a `dict` whose `"mode"` is exactly `"stream"`. Anything else passes
  through to normal parsing, including an existing `_ExecutionConfig` instance and a wrongly cased
  `"STREAM"`, which fails as an unknown enum member as it does today.
- `AKConfigError` is imported from `.util.factory`. That module imports only `importlib`,
  `contextlib` and `typing` (`core/util/factory.py:11-13`), so there is no import cycle.
- Pydantic 2.13.5 (the locked version) re-raises an exception from a model validator unchanged when
  it is neither `ValueError` nor `AssertionError`. So `AKConfig.get()` raises `AKConfigError`
  itself, not a `ValidationError`. This was checked against the locked version; the test in §Testing pins it.
- YAML, `AK_EXECUTION__MODE` (`env_nested_delimiter="__"`, `core/util/config_yaml_util.py:187`) and
  Helm `--set` all reach `_ExecutionConfig` as a dict, so one validator covers all three.
- Config loads lazily on the first `AKConfig.get()` (`core/config.py:1078-1099`), so "fails at
  config load" means the first `get()`: process startup for every entry point.

### §3 Pipeline (`pipeline/`)

**`IOHandler` (`io_handler.py`)**

- `run` (`:40`): line 85 and line 94 read `config.execution.is_websocket` instead of
  `mode in (ASYNC, STREAM)`. The startup log (`:95-98`) adds `message_type={execution.resolved_message_type}`.
- The warning at `:108-113` keeps its condition. Its text changes from "in ASYNC/STREAM" to "in
  async mode". Under `rest_sync + delta` with an `auth_validator`, this warning is the whole
  behaviour: `/ws` is not co-hosted.
- Runner selection (`:140-148`) checks `REALTIME` first, then `is_delta`:

  ```python
  if mode == ExecutionMode.REALTIME:
      runner = RealtimeAgentRunner()
  elif config.execution.is_delta:
      runner = StreamAgentRunner()
  else:
      runner = AgentRunner()
  ```

- `_validate_topology` (`:217-247`) drops its `mode` parameter: the only caller passes
  `config.execution.mode` (`:77-79`). New signature: `_validate_topology(cls, transport_type, config,
  auth_validator=None)`. Checks run in this order:
  1. `is_websocket` on `in_memory` without an `auth_validator`: the existing error, unchanged
     (`:220-224`). This now covers `async + delta`, which `stream` was exempt from.
  2. `is_websocket` on a broker without `websocket_api.push_auth_token`: the existing error (`:227-233`).
  3. A REST mode (`not is_websocket and mode != REALTIME`) on a broker with an `in_memory` or
     absent response store: the existing error (`:235-247`).
  4. **New:** `is_sse` on a broker whose store cannot hold chunks:
     `ResponseStoreFactory.create().supports_chunk_streaming()` is false. Error: "execution.mode
     rest_sync with message_type delta (SSE) on the <transport> transport needs a response store that
     can stream chunks; <type> cannot. Use a chunk-capable store, or execution.mode async with
     message_type delta (WebSocket)". Check 3 runs first, so an `in_memory` or absent store keeps its
     existing message. Building the store does not connect: the Redis and Valkey drivers connect
     lazily (`core/util/driver/redis_like.py:17-43`).
- The shared-connection-store check (`:85-92`) reads `is_websocket`. It stays in `run`, because it
  needs the session backend, not just config.

**`AgentRunner` / `StreamAgentRunner` (`agent_runner.py`)**

- `AgentRunner.run` (`:97-109`) checks `REALTIME`, then `config.execution.is_delta` for `StreamAgentRunner`.
- `StreamAgentRunner.process` (`:216-245`): the `USER_ID` check (`:222-223`) applies only when
  `execution.is_websocket` is true and the transport is not `in_memory`. Its message changes to
  "user_id is required in queue message attributes for async + delta over a broker transport".
  Under `rest_sync + delta`, a REST-entered message carries no `USER_ID` and is valid.
- The integration short-circuit (`:217-218`) and the thread-recording logic are unchanged.

**`ResponseHandler` (`response_handler.py`)**

- `process` (`:59-84`). The integration branches (`:61-69`) are unchanged. After them:

  ```python
  execution = AKConfig.get().execution
  if execution.is_websocket:
      kind = WebSocketHandlerABC.MessageType.STREAM_CHUNK if execution.is_delta else WebSocketHandlerABC.MessageType.CHAT_RESPONSE
      self._broadcast(message, kind)
      return
  if execution.is_sse:
      self._store_chunk(message)
      return
  self._store_response(message)
  ```

  The `ATTR_USER_ID` split (`:72-80`) is deleted. Every reply in a WebSocket mode is pushed, and
  every reply in SSE mode goes to the chunk store.
- `on_permanent_failure` (`:86-128`) mirrors this. The integration branch is unchanged.
  - `is_websocket and is_delta`: broadcast the error `StreamChunk` as `STREAM_CHUNK`.
  - `is_websocket`: broadcast `SYSTEM_RESPONSE`.
  - `is_sse`: `add_chunk` the error chunk, keeping the existing capability check and warning
    (`:110-114`).
  - Otherwise: store the 500 record.
  The `USER_ID` split at `:107` is deleted.
- `_store_chunk` (`:233-240`): only the error text changes, from "local STREAM delivery" to
  "rest_sync + delta (SSE) delivery".

**`RequestHandler` (`request_handler.py:226`)**

- `run_chat` (`:262-274`) branches on `self._config.execution.is_sse` instead of `_effective_mode() == STREAM`.
- `_reject_unroutable` (`:276-313`):
  - The `ASYNC` check reads `is_websocket`. It has the same 400 and message, and now covers
    `async + delta` too.
  - The `STREAM` check (`:304-313`) is deleted: `IOHandler` check 4 refuses that topology at
    startup. `RequestHandler` is `requires_pipeline` (`:236`), so it is only ever served by `IOHandler`.
  - The `REALTIME` check is unchanged.
- `_run_chat_stream`'s docstring (`:316`) names `IOHandler._validate_topology` as what guarantees the store.
- `_effective_mode` (`:245-247`) and the base `RestHandler.enqueue_and_wait` (`:125-175`) are unchanged.

**`WebSocketGateway._validate` (`ws/gateway.py:79`)**

- `:91-95` reads `if not config.execution.is_websocket`. The message changes from "serves
  ASYNC/STREAM modes" to "serves execution.mode async". The rest of the message is unchanged.

### §4 Direct REST, threads and A2UI

- `api/handler.py`: `run` (`:106`) and `run_multipart` (`:137`) branch on
  `Config.get().execution.is_sse`. The class docstring (`:81`) reads "streams SSE when
  execution.message_type is delta". Under `async`, with either message type, the direct handler
  keeps returning JSON as it does for `async` today. The direct path has never rejected `async`, and
  this change doesn't add that.
- `integration/thread/thread_chat.py`: `run` (`:78`) and `run_multipart` (`:109`) branch on
  `is_sse`, and the docstring at `:46` changes the same way.
- `a2ui/hook.py:115-120`: the warning condition becomes `getattr(AKConfig.get().execution, "is_delta",
  False)`. It keeps the defensive `getattr`, because the hook must never break the runtime. The text
  becomes "a2ui.enabled is true but execution.message_type is delta: ...". `realtime` still does not
  warn, as today.

### §5 AWS serverless (`deployment/aws/serverless/`)

- `aklambda.py:35-37`: `_is_websocket_mode` returns `Lambda._get_config().execution.is_websocket`.
- `core/router/rest_lambda.py`:
  - `DefaultEndpointsHandler.get_routes` (`:41`) starts with `if self._config.execution.is_sse:
    raise AKConfigError(...)`, before the direct/queue split. So both paths refuse.
    `RESTLambdaRouter.__init__` calls it (`:340`), so the failure happens at router init. Message:
    "execution.mode rest_sync with message_type delta (SSE) is not supported on AWS Lambda: the
    Lambda REST router does not stream responses. Use execution.mode async with message_type delta
    (WebSocket)". The message blames the router, not API Gateway: REST APIs can stream since
    Nov 2025, but Agent Kernel does not use it (design: Non-goals).
  - The `STREAM` branch (`:73-75`) and `_handle_stream` (`:299-315`) are deleted.
- `akagentrunner.py`:
  - `ServerlessAgentRunner.handle` (`:29-33`) dispatches to `ServerlessStreamAgentRunner` on `is_delta`.
  - `_get_record_attributes` (`:82`) reads `endpoint_url` when `is_websocket`.
  - The docstrings at `:16` and `:30` say "message_type delta".
  - The `ValueError` at `:279` says "endpoint_url is required for async + delta".
- `akresponsehandler.py`:
  - `process_message` (`:154-158`) broadcasts `STREAM_CHUNK` if `is_delta`, else `CHAT_RESPONSE`,
    when `is_websocket`; otherwise it stores the record.
  - `on_permanent_failure` (`:194`, `:211`) has the same split.
- `core/router/ws_lambda.py:281`: `_get_chat_handler_by_mode` picks `_handle_stream_direct` on `is_delta`.
- `core/webhook_host.py`: `LambdaWebhookGuard._check_mode` (`:116-122`) keeps the REST-mode check,
  then also requires `resolved_message_type == COMPLETE`. Message: "LambdaWebhookHost serves webhooks
  with execution.message_type complete only; got delta. Platform adapters deliver whole messages".

### §6 AWS containerized (`deployment/aws/containerized/`)

- `ecs_io_handler.py:47-58`:
  - `run` first raises `AKConfigError` when `is_sse`: "execution.mode rest_sync with message_type
    delta (SSE) is not served by the ECS deployment: its REST container (ECSQueueRequestHandler) has
    no SSE route. Use execution.mode async with message_type delta (WebSocket)".
  - The WebSocket branch then reads `is_websocket`.
  - The docstring (`:38-45`) and the `ValueError` text (`:53-57`) say "WebSocket (async) mode".
  - This applies whatever the store, because `ECSQueueRequestHandler` (`core/api/rest_api.py:6`) is
    the plain `RestHandler`, which waits for one record (`pipeline/request_handler.py:143-160`).
- `akoutputconsumer.py`: `process_message` (`:65-73`) and `on_permanent_failure` (`:108-116`) take the
  WebSocket path on `is_websocket`, with `STREAM_CHUNK` when `is_delta` and `CHAT_RESPONSE` /
  `SYSTEM_RESPONSE` otherwise. That replaces the `if ASYNC / elif STREAM / if in (ASYNC, STREAM)` triple.
- `akagentrunner.py`:
  - `ECSAgentRunner.run` (`:167-176`) checks `REALTIME` first, then `is_delta` for `ECSStreamAgentRunner`.
  - The docstrings at `:26` and `:169` and in `ECSStreamAgentRunner` (`:180-193`, `:199-201`) say "async + delta".
  - The `ValueError` at `:210` says "endpoint_url is required in SQS message attributes for async + delta".
- `core/api/websocket_api.py:418`: the direct WebSocket chat picks `_process_chat_direct_stream` on `is_delta`.

### §7 Terraform (`ak-deployment/ak-aws/`)

Both modules get the same variable:

```hcl
variable "message_type" {
  description = "Reply delivery: 'complete' (whole reply) or 'delta' (chunks: SSE under rest_sync, WebSocket under async). null leaves it to Agent Kernel's default (delta for realtime, complete otherwise). Injected as AK_EXECUTION__MESSAGE_TYPE."
  type        = string
  default     = null
  validation {
    condition     = contains(["complete", "delta"], coalesce(var.message_type, "complete")) # null passes
    error_message = "message_type must be null, 'complete' or 'delta'."
  }
}
```

The validation checks the value only. Combination rules stay in Python (design: Deployment).

**Serverless:**

- `variables.tf`:
  - `:56-62`: `execution_mode` drops `stream` from the condition and the description (`:58`). The
    `error_message` adds: "'stream' was removed: use rest_sync or async with message_type = \"delta\"".
  - `:65-66`: the non-queue condition drops `stream`.
  - The WebSocket conditions at `:124`, `:139`, `:150`, `:204`, `:214`, `:224`, `:235`, `:240`, `:253`,
    `:258`, `:263`, `:293`, `:314`, `:334` replace `contains(["async", "stream"], var.execution_mode)`
    with `var.execution_mode == "async"`. Their error messages drop "or 'stream'".
- `state.tf:39`: `is_websocket_mode = var.execution_mode == "async"`, and the comment is updated.
- `state.tf:633`, `:649`, `:738`: each `merge` adds `var.message_type != null ? {
  AK_EXECUTION__MESSAGE_TYPE = var.message_type } : {}` next to the `AK_EXECUTION__MODE` entry.

**Containerized:**

- `variables.tf`:
  - `:262-272`: `execution_mode` drops `stream` from both conditions and both messages, with the
    same migration hint. `realtime` stays.
  - The WebSocket conditions at `:66`, `:283`, `:287`, `:299`, `:303`, `:307` become `var.execution_mode == "async"`.
  - New `message_type` variable.
- `state.tf:24-25`: `is_websocket_mode = var.execution_mode == "async"`, and the comment is updated.
- `rest_service.tf:59` and `queue_mode.tf:70` pass `message_type = var.message_type` to the modules.
- `modules/rest-service/` and `modules/agent-runner/` each get a `message_type` variable
  (`rest-service/variables.tf` next to `:197`, `agent-runner/variables.tf` next to `:198`).
- Both containers get `AK_EXECUTION__MESSAGE_TYPE` whenever `message_type` is non-null, as its own
  `merge` entry outside the mode conditions. A separate entry also keeps a null value from rendering
  an empty env var.
  - `AK_EXECUTION__MODE` is injected only in some modes: WebSocket modes on the REST service
    (`rest-service/main.tf:42`), and `async`/`realtime` on the runner (`agent-runner/main.tf:39`).
    REST modes take the mode from `config.yaml`.
  - Inside those conditions, a REST-mode `message_type` would be dropped silently. In one container
    only, the two would disagree: the runner would emit chunks that the REST side stores as whole
    replies.
  - With both containers set, `rest_sync + delta` from Terraform reaches the `ECSIOHandler` startup
    refusal (§6).
- The condition at `agent-runner/main.tf:39` becomes `contains(["async", "realtime"], var.execution_mode)`.
- Comment-only wording ("async / stream") at `iam.tf:128`, `rest_service.tf:58`, `outputs.tf:94`,
  `modules/rest-service/main.tf:41` and `modules/agent-runner/main.tf:37`, and the variable
  descriptions at `modules/rest-service/variables.tf:199` and `modules/agent-runner/variables.tf:200`.

**Not touched:**

- `ak-deployment/ak-azure` and `ak-deployment/ak-gcp`: verified, neither injects
  `AK_EXECUTION__MODE` nor has an `execution_mode` variable. Their apps set the mode in `config.yaml`.
- `version = "..."` pins in examples and between modules. The release chore bumps them.

### §8 Helm chart (`ak-deployment/ak-k8s/chart/`)

- `values.yaml:61-64`: the comment lists `rest_sync | rest_async | async | realtime`. A commented
  `# messageType: delta` follows, with one line: "complete (default) or delta; async + delta pushes
  chunks over WebSocket".
- `templates/configmap-env.yaml:15`: after `AK_EXECUTION__MODE`:

  ```yaml
  {{- with .Values.execution.messageType }}
  AK_EXECUTION__MESSAGE_TYPE: {{ . | quote }}
  {{- end }}
  ```

- `.github/workflows/chart-test.yaml`:
  - `:78` becomes `--set execution.mode=async --set execution.messageType=delta`, and its output is
    grepped for `AK_EXECUTION__MESSAGE_TYPE: "delta"`.
  - `:116` becomes `--set execution.mode=async`.
- The chart validates neither value. A chart rendered with `mode=stream` deploys pods that fail at
  config load with the migration message.

### §9 Examples

The `version` pins are left alone (§7).

| Example | `config.yaml` | `deploy/main.tf` | Other |
| --- | --- | --- | --- |
| `api/pydanticai-streaming` | `mode: rest_sync`, `message_type: delta` | none | `app_test.py:5` docstring |
| `aws-containerized/openai-stream` | `mode: async`, `message_type: delta` | `execution_mode = "async"`, `message_type = "delta"` (`:27`) | README |
| `aws-containerized/openai-stream-queue-mode` | same | same (`:28`) | `app_agent_runner.py:29` comment, README |
| `aws-serverless/streaming-openai` | same | same (`:14`) | README |

- README-only mentions of `mode: stream` (`api/openai/README.md:80-85`, `api/hitl/README.md:209`,
  `aws-containerized/openai-websocket-scalable/README.md`, and the four `cli/*-run-options/README.md`
  tables) get the matching pair.
- `k8s/openai-queue-mode/README.md:199-215`: the WebSocket section's `--set execution.mode=stream`
  becomes `--set execution.mode=async --set execution.messageType=delta`, and its prose says
  `async + delta`.
- `api/agui/config.yaml:2-3` and its README say AG-UI does not read the mode, so only the wording changes.

### §10 Components and module-level code

- No new class. The predicates are properties on `_ExecutionConfig`, the class that owns the
  section. The startup checks are methods on the entry points that own each topology: `IOHandler`,
  `ECSIOHandler`, `DefaultEndpointsHandler` and `LambdaWebhookGuard`.
- No new module-level function.

### §11 Concurrency and per-operation cost

- The predicates are pure reads of an `_ExecutionConfig` that nothing mutates after load, so they
  are safe across `ThreadRunner` threads and the ECS consumer threads.
- On hot paths (`ResponseHandler.process`, the output consumers, `run_chat`), one or two enum
  comparisons replace one. Each site still calls `AKConfig.get()` once, as today.
- `IOHandler` check 4 builds one response store at startup, and only for `rest_sync + delta` on a
  broker. It does not connect.

## Consumer changes

| Consumer | Deleted | Changed | Unchanged |
| --- | --- | --- | --- |
| Pipeline single process (`IOHandler`, `in_memory`) | `stream` co-hosting SSE and `/ws` in one process | `rest_sync + delta`: SSE only; `async + delta`: `/ws` only, `auth_validator` required | `rest_sync`, `rest_async`, `async`, `realtime` with the default message type |
| Pipeline broker (`IOHandler` + `AgentRunner` + `WebSocketGateway`) | per-request 400 for SSE without a chunk store | startup error instead; `async + delta` is today's broker `stream` | every other mode |
| Direct REST (`AgentRESTRequestHandler`, threads) | none | SSE when `is_sse` | JSON for every other combination, `async` included |
| ECS (queue and direct) | none | `async + delta` is today's `stream`; `rest_sync + delta` refused at startup | everything else |
| AWS Lambda (REST, WS, runner, response handler) | dead `STREAM` branch, `_handle_stream` | `async + delta` is today's `stream`; `rest_sync + delta` refused at router init | everything else |
| `LambdaWebhookHost` | none | refuses `message_type: delta` | REST-mode check |
| Messaging integrations (webhooks, pollers, gateways) | none | none | whole replies, routed before any mode check (`response_handler.py:66`, `agent_runner.py:217`) |
| Helm / Terraform | `stream` as an accepted value | new `messageType` / `message_type` input | everything else |

## Config changes

- `execution.mode`: same name, type `Optional[ExecutionMode]` and default `None`. The value
  `stream` is removed, and the description changes (§2).
- `execution.message_type`: new, `Optional[ReplyMessageType]`, default `None`. Env var
  `AK_EXECUTION__MESSAGE_TYPE`.
  - Why it can't be derived: `async + complete` and `async + delta` (and `rest_sync + complete` and
    `rest_sync + delta`) differ only in this field.
  - Readers: the four predicates only (§2 rule 1).
- Reuse: no other model fits. `message_type` lives on `_ExecutionConfig` next to `mode`, and the
  existing `queues`, `response_store` and `realtime` blocks are untouched.
- No `enabled` flag and no new block.
- Existing YAML and env:
  - Every value except `mode: stream` loads unchanged and resolves to the same behaviour.
  - `mode: stream` (YAML, `AK_EXECUTION__MODE=stream`, Helm `execution.mode=stream`) raises
    `AKConfigError` with `STREAM_MIGRATION_MESSAGE` on the first `AKConfig.get()`.
- Persisted data: none of it depends on the mode, so there is nothing to migrate.
  - Response-store records and chunk frames keep their shape.
  - Output messages in flight during a rolling deploy are read the same way: a `stream` runner's
    chunks reach an `async + delta` handler as `STREAM_CHUNK`, as before.

## Behavioural changes

All intentional, from the design.

1. **`execution.mode: stream` fails at config load**, from YAML, env and Helm, with the two-line
   migration message. Breaking config change, so the release notes carry the migration.
2. **`ExecutionMode.STREAM` is removed from the Python API.** User code referencing it raises
   `AttributeError`. Breaking API change, in the release notes with item 1.
3. **No single process serves SSE and WebSocket together.** Today's `stream` on `in_memory` with an
   `auth_validator` served REST requests over SSE and WS requests over `/ws`, split by `ATTR_USER_ID`
   (`response_handler.py:72-80`).
   - `rest_sync + delta` serves SSE only. Passing an `auth_validator` logs the existing warning.
   - `async + delta` serves `/ws` only. The REST chat route returns the `async` 400.
4. **`async + delta` on `in_memory` requires an `auth_validator`**, as `async` does. `stream` did
   not (`io_handler.py:220`).
5. **Routing no longer reads `ATTR_USER_ID`.** `ResponseHandler` routes on the config pair alone.
   `StreamAgentRunner` requires `USER_ID` only for `async + delta` on a broker.
6. **`rest_sync + delta` on a broker without a chunk-capable store fails at `IOHandler` startup**.
   Today it is a 400 on every request (`request_handler.py:304-313`), and that per-request check is deleted.
7. **ECS refuses `rest_sync + delta` at startup.** This is a new combination, so nothing worked
   before. Today's ECS `stream` is WebSocket and maps to `async + delta`.
8. **The Lambda REST router refuses `rest_sync + delta` at init.** Its dead `STREAM` branch and
   `_handle_stream` are deleted. They were unreachable, because `aklambda.py:37` sends `stream` to
   the WS router.
9. **`LambdaWebhookHost` refuses `message_type: delta`.**
10. **`rest_async + delta` and `realtime + complete` fail at config load.**
11. **Message text** that said "ASYNC/STREAM" or "STREAM" now says "async" or names the pair:
    - the `WebSocketGateway` mode error;
    - the `IOHandler` warning;
    - the `ECSIOHandler` `ValueError`;
    - the `_store_chunk` and `StreamAgentRunner` `ValueError`s;
    - the serverless and ECS runners' `endpoint_url` `ValueError`s (§5, §6);
    - the A2UI warning.
12. **Terraform `execution_mode = "stream"` fails at `terraform plan`** with the migration hint.
    Both modules accept `message_type`.

**Non-changes:**

- `StreamChunk`, SSE framing, the WS message types (`STREAM_CHUNK`, `CHAT_RESPONSE`, `SYSTEM_RESPONSE`)
  and the response-store chunk API (`add_chunk`, `stream`, `supports_chunk_streaming`).
- `realtime` behaviour, runners and delivery, and the `execution.realtime` block.
- Integration delivery (non-realtime replies are whole, whatever the message type), and
  `IntegrationDelivery` itself.
- Unset `mode`: still `rest_sync` in the pipeline (`request_handler.py:247`) and the REST path elsewhere.
- The direct REST handler under `async` (JSON).
- Public exports and the signatures of every public method. The one signature change is the private
  `IOHandler._validate_topology`, which drops its redundant `mode` parameter.

## Error handling

| Failure | Where | Surfaces as |
| --- | --- | --- |
| `mode: stream` | `_ExecutionConfig._reject_legacy_stream`, first `AKConfig.get()` | `AKConfigError(STREAM_MIGRATION_MESSAGE)`; process fails to start |
| `rest_async + delta`, `realtime + complete` | `_ExecutionConfig._check_message_type` | `AKConfigError` naming both fields and the valid alternatives |
| Unknown `message_type` value | Pydantic enum parsing | `ValidationError` (standard, as for an unknown `mode`) |
| `async` (either type) on `in_memory` without `auth_validator` | `IOHandler._validate_topology` check 1 | existing `AKConfigError` |
| `rest_sync + delta` on a broker without a chunk store | `IOHandler._validate_topology` check 4 | `AKConfigError` naming the pair and both fixes |
| `rest_sync + delta` on ECS | `ECSIOHandler.run` | `AKConfigError` naming `async + delta` |
| `rest_sync + delta` on Lambda | `DefaultEndpointsHandler.get_routes` (router init) | `AKConfigError` naming `async + delta` |
| `message_type: delta` with `LambdaWebhookHost` | `LambdaWebhookGuard._check_mode` | `AKConfigError` |
| `message_type` not `complete`/`delta`/null in Terraform | variable validation | `terraform plan` error |
| `async + delta` message without `USER_ID` on a broker | `StreamAgentRunner.process` | `ValueError` per message (as today for `stream`); redelivered, then permanent failure |

No new optional dependency and no new exception type.

## Testing

Run from `ak-py/`: `uv run pytest`. CI also runs `chart-test.yaml`, and `terraform fmt -check` /
`terraform validate` cover the two AWS modules.

### New tests

- **`tests/test_config.py`** (existing file; this follows its `reset_config_singleton` fixture and
  `tmp_path` YAML pattern, `:11`, `:31`):
  - Every matrix cell, parametrized over `mode` × `message_type` (including unset), asserting it
    loads or raises `AKConfigError` with both field names in the message.
  - The defaults: `resolved_message_type` is `COMPLETE` for unset, `rest_sync`, `rest_async` and
    `async`, and `DELTA` for `realtime`.
  - A predicate table: `is_websocket`, `is_delta` and `is_sse` for each valid cell. `realtime` is
    `is_delta == False`.
  - `mode: stream` from YAML and from `AK_EXECUTION__MODE=stream`: `AKConfig.get()` raises
    `AKConfigError` (not `ValidationError`), and the message contains both "rest_sync" and "async"
    next to "message_type: delta".
  - `AK_EXECUTION__MESSAGE_TYPE=delta` with `AK_EXECUTION__MODE=async` loads as `async + delta`.
- **`tests/test_pipeline_io_handler.py`**:
  - `rest_sync + delta` on `in_memory` with an `auth_validator`: no `/ws` route mounted, the warning
    is logged, and `StreamAgentRunner` is selected.
  - `async + delta` on `in_memory` without a validator raises.
  - `rest_sync + delta` on `nats` with a `redis` store type raises check 4 when
    `ResponseStoreFactory.create` is patched to return a store without chunk capability. It passes
    when the patched store has it, so the test survives #755 giving Redis the capability.
  - `realtime` selects `RealtimeAgentRunner`, not `StreamAgentRunner`.
- **`tests/test_pipeline_request_handler.py`**: `rest_sync + delta` serves `text/event-stream` (the
  existing SSE tests at `:199`, `:379`, `:433` move to it). `async + delta` gets the `async` 400 on
  `POST /api/v1/chat`.
- **`tests/test_pipeline_response_handler.py`**: `async + delta` broadcasts `STREAM_CHUNK` with and
  without `USER_ID`. `rest_sync + delta` stores chunks with and without `USER_ID`. Permanent
  failure covers both.
- **`tests/test_lambda_router.py`**: `rest_sync + delta` makes `RESTLambdaRouter()` raise
  `AKConfigError`, with and without queues. `test_handle_stream_returns_400_not_raises` (`:109`) is
  deleted with `_handle_stream`.
- **`tests/test_ecs_io_handler.py`**: `rest_sync + delta` raises before any thread starts.
- **`tests/test_lambda_webhook_host.py`**: `rest_sync + delta` is refused by `_check_mode`, and
  `rest_sync` and `rest_async` with `complete` pass. The existing parametrization at `:302` drops `"stream"`.
- **Direct REST** (`tests/test_api_multipart_fields.py`, the riskiest consumer: it has no SSE test
  today): `rest_sync + delta` returns `text/event-stream`, and `async + delta` returns JSON.

### Existing tests that change

31 mode hits in 12 files. Two other `"stream"` matches are not modes and are not touched:
`test_smolagents_runner.py:270` (a run-options key) and `test_pipeline_request_handler.py:439` (it
patches the store's `stream` method).

- `test_pipeline_io_handler.py:70`, `:92`, `:96`: `_validate_topology` loses its `mode` argument at
  every call (`:62-96`). The `STREAM` cases become `async + delta` (`:70`, `:92`) and
  `rest_sync + delta` (`:96`), because `async + delta` on `in_memory` now needs a validator.
- `test_pipeline_response_handler.py:120`, `:131`, `:143`, `:154`, `:226`: the `USER_ID`-split tests
  become the two pair tests above.
- `test_pipeline_request_handler.py:199`, `:379`, `:433`, and `test_thread_pipeline_recording.py:208`,
  `:350`, `:360`, `:368`: `_configure(monkeypatch, mode="stream")` becomes `mode="rest_sync",
  message_type="delta"`. The helpers set `AK_EXECUTION__MESSAGE_TYPE` next to `AK_EXECUTION__MODE`
  (`test_pipeline_request_handler.py:84`, `test_thread_pipeline_recording.py:100`).
- `test_pipeline_ws.py:558`, `:623`, `test_ecs_websocket_routes.py:417`, `:450`,
  `test_ecs_akoutputconsumer.py:43`, `test_akresponsehandler.py:90`, `test_ws_lambda_stream.py:53`,
  `:64`, `:86`, `:125`, `:157`, `:187`, `test_serverless_integration_delivery.py:236`, `:323`: `STREAM`
  becomes `async + delta`.
- `test_a2ui_hook.py:181`: `mode="stream"` becomes `message_type="delta"`. A `realtime` case asserts
  that no warning is logged.
- `test_lambda_webhook_host.py:302`: drop `"stream"`.

**Config fakes.** 24 test files stub `execution` by hand: `SimpleNamespace`, plain classes, or
`MagicMock`. On a `MagicMock`, `execution.is_sse` is a truthy mock. On a plain class it is an
`AttributeError`. Every fake whose code path reaches a changed call site builds a real
`_ExecutionConfig(mode=..., message_type=...)` and then sets the attributes it needs (`queues`,
`response_store`) on that instance. That covers the 12 files above plus at least:

- `test_api_multipart_fields.py:29`
- `test_rest_handler_poll.py:34`, `:96`
- `test_serverless_status_propagation.py:103`
- `test_realtime_pool.py:290`, `:2170`, `:2249`, `:2277`
- `test_ecs_io_handler.py`
- `test_ecs_output_consumer_status.py`
- `test_pipeline_agent_runner.py`
- `test_ecs_akagentrunner_realtime.py`

Fakes that only stub `queues` for transport tests (`test_pipeline_*_transport.py`,
`test_pipeline_consumer_loop.py`, `test_response_store_*.py`, `test_runtime.py`) reach no changed
site and stay as they are. A full `uv run pytest` run is the check.
