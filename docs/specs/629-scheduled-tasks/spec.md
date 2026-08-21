# #629: Scheduling capability for deferred and recurring chat execution: Implementation Spec

This spec details the implementation of the scheduling capability approved in `design.md`: a `schedule` block on the chat payload intercepted in the ChatService execution core, a `ScheduleProvider` / `ScheduleStore` pair orchestrated by a `ScheduleManager` singleton, a management REST handler, five agent system tools, trigger delivery straight into the input queue, a shared-authorization refactor, and AWS Terraform provisioning. `design.md` is the requirements source; `research/aws-eventbridge-scheduler.md` holds the verified AWS facts. All `path:line` citations are against `develop` at the time of writing.

## Design

### Package layout

New top-level package (sibling of `sandbox/`):

```
ak-py/src/agentkernel/schedule/
├── __init__.py          # public: ScheduleManager, ScheduleSpec (re-export), ScheduledTask,
│                        #   ScheduleStatus, ScheduleProvider, ScheduleStore, ScheduleError,
│                        #   ScheduleRESTRequestHandler; tools/factories stay internal
├── model.py             # ScheduledTask, ScheduledTaskPage, ScheduleStatus, body-token constants
├── errors.py            # ScheduleError(Exception)
├── manager.py           # ScheduleManager singleton (validation, ownership, trigger bodies, recording)
├── handler.py           # ScheduleRESTRequestHandler (imports fastapi; never imported by core)
├── tools.py             # get_schedule_tools() (internal, reached via SystemToolFactory)
├── provider/
│   ├── __init__.py
│   ├── base.py          # ScheduleProvider ABC + ScheduleProviderFactory
│   ├── local.py         # LocalScheduleProvider (in-process timers, default)
│   └── eventbridge.py   # EventBridgeScheduleProvider (aws extra)
└── store/
    ├── __init__.py
    ├── base.py          # ScheduleStore ABC + ScheduleStoreBuilder
    ├── in_memory.py     # InMemoryScheduleStore
    ├── redis_like.py    # _RedisLikeScheduleStore shared body
    ├── redis.py         # RedisScheduleStore
    ├── valkey.py        # ValkeyScheduleStore
    └── dynamodb.py      # DynamoDBScheduleStore
```

Governing rules:

1. **Core reaches `schedule/` only lazily, inside enabled-checks**: the ChatService interception helper and the `SystemToolFactory` block import inside the `if` (the sandbox precedent, `core/tool.py:190,196`). `schedule/handler.py` imports FastAPI and `api/handler.py`; nothing in `core/` imports it. `schedule/manager.py`, `model.py`, `provider/`, `store/` import only `core` and `pipeline` (transport factory + envelope).
2. **Providers and stores never read `AKConfig` in methods**: `ScheduleProviderFactory` / `ScheduleStoreBuilder` read config once and pass explicit constructor parameters (the shared-driver rule, and pipeline transport rule 4).
3. **Everything that travels in a queue body is a JSON primitive**: `ScheduleSpec` fields and trigger bodies are strings/ints only, because both queue paths serialize with python-mode `model_dump()` + `json.dumps` (`pipeline/request_handler.py:86,200`; `deployment/aws/core/sqs_handler.py:91-107`). `ScheduledTask` timestamps are ISO-8601 UTC strings for the same reason (store portability).
4. **Tools never raise into the framework** (`sandbox/tools.py:1-10`); the manager raises typed errors (`ValueError` validation, `PermissionError` ownership, `ScheduleError` provider failures); handlers map them to 400/403/404/500.

### Wire models (`core/model.py`)

`ScheduleSpec` is part of the chat envelope, so it lives in `core/model.py` beside `BaseChatRequest` (`core/model.py:201-214`); the `schedule/` package imports it from core. This keeps the coupling direction intact (core never imports `schedule/` eagerly).

```python
class ScheduleSpec(BaseModel):
    """Schedule block on a chat request: defer execution instead of running now."""
    at: Optional[str] = None            # ISO-8601 local wall-clock timestamp: one-time
    cron: Optional[str] = None          # standard 5-field cron expression: recurring
    timezone: str = "UTC"               # IANA timezone the expression is evaluated in
    session_mode: Literal["reuse", "new"] = "reuse"

    @model_validator(mode="after")
    def _exactly_one_occurrence(self): ...   # exactly one of at/cron, else ValueError
```

Structural validation only lives here (one-of, literal, non-empty timezone). Semantic validation (cron syntax via `croniter`, timezone via `zoneinfo`, `at` parseable and in the future) lives in `ScheduleManager`, because `croniter` is an optional dependency and core models must import clean.

Field additions:

- `BaseChatRequest.schedule: Optional[ScheduleSpec] = None` (`core/model.py:209-214`). All envelope carriers inherit it: `BaseRunRequest`, `BaseMultimodalRunRequest` (`api/handler.py:50-55`), the serverless/WS `BaseRequest.body` (`core/model.py:225-264`).
- `BaseRunRequest` gains two typed trigger-metadata fields (`core/model.py:217-222`): `scheduled_task_id: Optional[str] = None` and `scheduled_time: Optional[str] = None`. Trigger bodies also carry `request_id`, which `extra="allow"` already preserves as an attribute.
- `RequestBuilder._attach_additional_context` `known_fields` (`core/chat_service.py:126`) gains `"schedule"`, `"scheduled_task_id"`, `"scheduled_time"` so none of them leaks to the agent as `AgentRequestAny` (today an unknown `schedule` key does leak; see Behavioural changes 1 and 2).

### Task model (`schedule/model.py`)

```python
class ScheduleStatus(str, Enum):
    ACTIVE = "active"; PAUSED = "paused"; COMPLETED = "completed"; CANCELLED = "cancelled"

class ScheduledTask(BaseModel):
    task_id: str                      # AK-minted uuid4
    user_id: str                      # owner (required: creation enforces it)
    prompt: str
    agent: Optional[str] = None
    session_id: str                   # originating session (reuse) / template base (new)
    spec: ScheduleSpec
    status: ScheduleStatus = ScheduleStatus.ACTIVE
    provider_ref: Optional[str] = None    # e.g. EventBridge schedule ARN; task_id for local
    created_at: str; updated_at: str      # ISO-8601 UTC strings (rule 3)
    last_triggered_at: Optional[str] = None
    trigger_count: int = 0
    last_request_id: Optional[str] = None  # request_id of the most recent occurrence

class ScheduledTaskPage(BaseModel):
    tasks: List[ScheduledTask]; next_cursor: Optional[str] = None
```

Body-token constants (substituted per provider, see Trigger bodies):

```python
TOKEN_REQUEST_ID = "{ak.schedule.request_id}"
TOKEN_OCCURRENCE_TIME = "{ak.schedule.occurrence_time}"
```

The amendable set (PUT and `update_schedule`): `at`, `cron`, `timezone`, `session_mode`, `prompt`, plus `status` restricted to `active`/`paused`.

### ChatService interception (`core/chat_service.py`)

Two private helpers on `ChatService`; the four execution-core entry points (`execute` :338, `execute_sync` :356, `execute_stream` :370, `execute_stream_sync` :395) each gain two calls at the top:

```python
def _maybe_schedule(self, req) -> Optional[AgentReplyAny]:
    if getattr(req, "schedule", None) is None:
        return None
    from ..schedule.manager import ScheduleManager  # lazy (rule 1)
    manager = ScheduleManager.get()
    if manager is None:
        raise ValueError("Scheduling is not configured. Add a 'schedule' block to config.yaml")
    task = manager.create_from_request(req)
    return AgentReplyAny(content={"status": "SCHEDULED", "scheduled_task_id": task.task_id,
                                  "session_id": task.session_id})

def _record_trigger(self, req) -> None:          # never raises: log-and-continue
    task_id = getattr(req, "scheduled_task_id", None)
    if not task_id: return
    from ..schedule.manager import ScheduleManager
    manager = ScheduleManager.get()
    if manager is not None:
        manager.record_trigger(task_id, request_id=getattr(req, "request_id", None),
                               occurred_at=getattr(req, "scheduled_time", None))
```

Entry-point wiring (identical shape in all four):

- `execute` / `execute_sync`: `scheduled = self._maybe_schedule(req); if scheduled is not None: return scheduled, req.session_id`. Then `self._record_trigger(req)`, then the existing `_prepare_* / AgentHandler` flow, unchanged.
- `execute_stream` / `execute_stream_sync`: when scheduled, return a generator yielding exactly one terminal chunk: `StreamChunk(delta=str(ack), done=True)` where `str(ack)` is the JSON-serialized acknowledgement (`AgentReplyAny.__str__`, `core/model.py:140-141`). Not an error chunk (design decision). Otherwise identical wiring.
- The scheduled return for `execute`/`execute_sync` uses `req.session_id` as the response session id (no agent/session was selected).

**202 plumbing**:

- `process_chat_request` / `process_async_chat_request` (`chat_service.py:441-474`): success status becomes `202 if getattr(req, "schedule", None) is not None else 200`.
- `ResponseBuilder.build_response` (`chat_service.py:286-311`): in `rest_api_mode`, a success with `status_code != 200` returns `fastapi.responses.JSONResponse(content=response_dict, status_code=status_code)` (lazy FastAPI import, same pattern as the existing `HTTPException` import at :307). The non-rest tuple path is unchanged: `(202, dict)` flows to the queue runners, which already forward it as the `STATUS_CODE` attribute (`pipeline/agent_runner.py:98-99`).
- Streaming wrappers are unchanged: the terminal chunk rides the existing SSE framing.

**Thread handler** (`integration/thread/thread_chat.py`): both `_run_with_recording` (:110) and `_stream_with_recording` (:133) check `req.schedule` after `_validate_chat_request` + `_check_agent_available` and **before** `ThreadRecorder.pre_run`:

- Non-stream: `result, session_id = await self.chat_service.execute(req); return ResponseBuilder.build_response(202, session_id, True, result=result)`. No thread, no message records.
- Stream: return the (single-terminal-chunk) generator from `self.chat_service.execute_stream(req)` framed as SSE, skipping `pre_run`/`post_run`.

The agent-availability precheck stays in front deliberately: a schedule whose agent does not exist should fail at creation, not at fire time.

### Acting-user propagation (`core/runtime.py`) — shipped in Phase 2

The acting user is **not** poked into the volatile cache from `ChatService`. `ACTING_USER_CACHE_KEY` lives in `core/runtime.py:34` (re-exported from `core/__init__.py`), and `acting_user_id` is threaded as an explicit optional parameter down the execution chain:

`ChatService.execute*` (`chat_service.py:353,367,388,412` — passing `req.user_id`) → `AgentHandler.run_async` / `run_sync` / `run_stream_async` / `run_stream_sync` (`chat_service.py:227-270`) → `AgentService.run_multi` / `stream_multi` (`core/service.py:139,157`) → `Runtime.run` / `Runtime.stream` (`core/runtime.py:189,233`).

`Runtime` performs the only cache write, **inside** `async with session:` (`core/runtime.py:207-208`, `250-252`):

```python
async with session:
    try:
        if acting_user_id:
            session.get_volatile_cache().set(ACTING_USER_CACHE_KEY, acting_user_id)
        ...
    finally:
        session.get_volatile_cache().clear()
```

Set and clear are therefore serialized by the same per-session lock, so concurrent same-session runs on one session cannot have one run's `finally` clear another run's acting user. The key stays per-run.

Consumers (the Phase 4 schedule tools) read it with `Session.current().get_volatile_cache().get(ACTING_USER_CACHE_KEY)`, importing the constant from `core.runtime` (or `core`).

### ScheduleManager (`schedule/manager.py`)

Singleton in the `ConversationThreadManager` / `ExecutionManager` shape (`integration/thread/manager.py:77-90`, `sandbox/manager.py:53-63`):

```python
class ScheduleManager:
    _instance: ClassVar[Optional["ScheduleManager"]] = None
    _lock: ClassVar[RLock] = RLock()

    def __init__(self, provider: ScheduleProvider, store: ScheduleStore): ...

    @classmethod
    def get(cls) -> Optional["ScheduleManager"]:
        # None when AKConfig.get().schedule is None (feature-disabled signal);
        # otherwise build under the lock: ScheduleStoreBuilder.build() +
        # ScheduleProviderFactory.create(), then _validate_transport_compatibility().
    @classmethod
    def reset(cls) -> None: ...                    # testing

    def create_from_request(self, req: BaseChatRequest) -> ScheduledTask   # chat path
    def create(self, user_id, prompt, spec, agent=None, session_id=None) -> ScheduledTask  # tools path
    def get_task(self, task_id, user_id=None) -> Optional[ScheduledTask]
    def list_tasks(self, user_id=None, limit=None, cursor=None) -> ScheduledTaskPage
    def update(self, task_id, amendment: dict, user_id=None) -> ScheduledTask
    def cancel(self, task_id, user_id=None) -> ScheduledTask
    def record_trigger(self, task_id, request_id=None, occurred_at=None) -> None
```

- **Transport compatibility (fail-fast)**: at construction, when `provider.supported_transports is not None` and `QueueTransportFactory.resolve_type()` (`pipeline/transport/base.py:72-87`) is not in the set, raise `AKConfigError("schedule provider 'eventbridge' delivers to 'sqs' transports, but the configured queue transport is 'in_memory'")`. `resolve_type()` is used (not `create()`) because it returns the declared or URL-implied type even where the pipeline transport class has not shipped (ECS today).
- **Local-provider single-process constraint (fail-fast)**: at construction, when `AKConfig.get().schedule.provider.type.lower() == "local"` and either `QueueTransportFactory.resolve_type()` or `schedule.store.type.lower()` is not `in_memory`, raise `AKConfigError("schedule provider 'local' is single-process only: it requires the 'in_memory' queue transport and the 'in_memory' store, but the configured transport is 'sqs' and the store is 'in_memory'")`. A separate method (`_validate_local_provider_topology`) from the transport check above, because the two fail for different reasons: `local` + `sqs` *delivers* correctly and is only unmanageable — the armed heap lives in the agent-runner process while the management routes are served by IOHandler. Returns early when `AKConfig.get().schedule` is `None`, the only path being a caller that injected its own backends (`get()` never does). Keyed on the `local` short name rather than a capability declared on the ABCs: `local` is the sole built-in provider, so no reachable configuration escapes it, and no ABC change is needed.
- **Creation** (`create_from_request` validates `req.user_id` and delegates): validate spec semantically (croniter parse of `cron`; `zoneinfo.ZoneInfo(timezone)`; `at` parses via `datetime.fromisoformat`, rejects an explicit UTC offset, and must be in the future in its timezone; `user_id` required) → mint `task_id` → build the `ScheduledTask` and trigger-body template → `store.create(task)` → `provider.create(task, body_template)` → `store.update(task with provider_ref)`. On provider failure: `store.delete(task_id)` (hard delete, rollback only) and re-raise. Design order preserved: record first, provider second, no active record without a provider registration surviving an error.
- **Amendment** (`update`): load + ownership check → reject when `status` in (`completed`, `cancelled`) with `ValueError` → apply the amendable fields (semantic re-validation) → `store.update` → `provider.update` (which re-freezes the trigger body; pause/resume maps to provider state). On provider failure the store change is rolled back to the previous record and the error re-raised.
- **Cancel**: ownership check → `provider.delete(provider_ref)` (tolerates already-gone) → `store.update(status=CANCELLED)`. Soft transition: the record is the audit trail.
- **Ownership**: `get_task`/`update`/`cancel` raise `PermissionError` when `user_id is not None and task.user_id != user_id` (the thread convention, `integration/thread/manager.py:251-252`); `list_tasks` filters by owner.
- **record_trigger**: `store.record_trigger(task_id, request_id, occurred_at or now)` updating `last_triggered_at`, `trigger_count += 1`, `last_request_id`; a one-time task (spec has `at`) also moves to `COMPLETED`. Wrapped in `try/except Exception: log`: recording never fails a run.
- **Pagination**: cursor/limit helpers move to a new shared `core/util/pagination.py` (`encode_cursor`, `decode_cursor`, `clamp_limit`) extracted verbatim from `integration/thread/manager.py:27-54`; the thread manager is refactored to call them (behavior identical: base64 offset cursor, `ValueError("Invalid pagination cursor")`, default 50 / max 200). `ScheduleManager` uses the same helpers.

### Trigger bodies and delivery

The manager freezes the trigger body at create/amend time as a JSON string template:

```json
{"prompt": "...", "agent": "...", "user_id": "...",
 "session_id": "<see session_mode>",
 "scheduled_task_id": "<task_id>",
 "request_id": "{ak.schedule.request_id}",
 "scheduled_time": "{ak.schedule.occurrence_time}"}
```

- `session_mode: reuse` → `session_id` is the originating id; FIFO `MessageGroupId` is that id (ordering against live session traffic preserved).
- `session_mode: new` → `session_id` is `"ak-sched-<task_id>-{ak.schedule.occurrence_time}"`; `MessageGroupId` is the `task_id`.
- No `schedule` block in the body: the trigger executes as a plain chat request (loop prevention).
- Token substitution is provider-owned: EventBridge textually replaces the tokens with `<aws.scheduler.execution-id>` / `<aws.scheduler.scheduled-time>` at registration (AWS resolves them at fire time; verified in `research/aws-eventbridge-scheduler.md`); the local provider substitutes `str(uuid.uuid4())` and the ISO occurrence time at fire time.
- **Metadata travels in the body, never in message attributes**: EventBridge cannot set SQS message attributes, and the local provider deliberately matches that (one delivery contract, and the in-memory pipeline then exercises the same body-fallback path AWS uses).

### ScheduleProvider (`schedule/provider/base.py`)

```python
class ScheduleProvider(ABC):
    supported_transports: ClassVar[Optional[frozenset[str]]] = None  # None = transport-agnostic

    @abstractmethod
    def create(self, task: ScheduledTask, body_template: str) -> str: ...   # returns provider_ref
    @abstractmethod
    def update(self, task: ScheduledTask, body_template: str) -> None: ...
    @abstractmethod
    def delete(self, provider_ref: str) -> None: ...                        # idempotent
    @abstractmethod
    def get(self, provider_ref: str) -> Optional[dict]: ...                 # native details, None if gone

class ScheduleProviderFactory:
    _BUILTIN_TYPES = ("local", "eventbridge")
    @classmethod
    def create(cls) -> ScheduleProvider: ...
    # local: plain import; eventbridge: require_extra("aws", "schedule.provider.type: eventbridge");
    # dotted path via resolve_dotted(base=ScheduleProvider); unknown short name -> AKConfigError
    # naming the built-ins (the ThreadStoreBuilder shape, integration/thread/store/base.py:130-189)
```

**LocalScheduleProvider** (`provider/local.py`), `supported_transports = None`:

- One daemon scheduler thread per process (started lazily on first `create`), a min-heap of `(next_fire_epoch, task_id)` guarded by a `threading.Condition`; `create`/`update`/`delete` adjust the heap and notify. `croniter` computes the next fire from `cron` + `zoneinfo` timezone; `at` is a single entry.
- Firing: substitute tokens, then `QueueTransportFactory.create().send(QueueName.INPUT, QueueMessage(body=body_json, attributes={}, group_id=<per session_mode>, dedup_id=None))`. Empty attributes by design (see Trigger bodies). Send failures are logged and the occurrence skipped (next occurrence still armed).
- One-time entries fire once and drop out; recurring re-arm with the next cron fire. Paused/cancelled tasks are removed from the heap. No re-arming after process restart (documented non-goal).
- `provider_ref` is the `task_id`; `get` returns the next armed fire time or `None`.

**EventBridgeScheduleProvider** (`provider/eventbridge.py`), `supported_transports = frozenset({"sqs"})`, `aws` extra:

- Constructor parameters (from `schedule.provider.eventbridge`, read by the factory): `group_name`, `role_arn`, `queue_arn`. All three required: missing → `AKConfigError` at factory time.
- `create` → `boto3.client("scheduler").create_schedule` with `Name=f"ak-{task_id}"`, `GroupName`, `ScheduleExpression`, `ScheduleExpressionTimezone=spec.timezone`, `FlexibleTimeWindow={"Mode": "OFF"}`, `ActionAfterCompletion="DELETE"` for one-time / `"NONE"` for cron, `State="ENABLED"|"DISABLED"` from task status, `Target={"Arn": queue_arn, "RoleArn": role_arn, "Input": body, "SqsParameters": {"MessageGroupId": group}}`. Returns the `ScheduleArn` as `provider_ref`.
- Expression mapping: `at` → `at(yyyy-mm-ddThh:mm:ss)`; 5-field cron → 6-field AWS flavor: append year `*`, and apply the day-field rule (both day-of-month and day-of-week `*` → day-of-week becomes `?`; one specified → the other becomes `?`; both specified → `ValueError`, AWS disallows it).
- `update` → `update_schedule` (full target re-sent); `delete` → `delete_schedule`, swallowing `ResourceNotFoundException` (one-time schedules self-delete via `ActionAfterCompletion`); `get` → `get_schedule`, `None` on `ResourceNotFoundException`.
- `botocore.exceptions.ClientError` (other than the tolerated not-found on delete/get) is wrapped in `ScheduleError` carrying the AWS error message.

### ScheduleStore (`schedule/store/base.py`)

```python
class ScheduleStore(ABC):
    @abstractmethod
    def create(self, task: ScheduledTask) -> ScheduledTask: ...
    @abstractmethod
    def get(self, task_id: str) -> Optional[ScheduledTask]: ...
    @abstractmethod
    def update(self, task: ScheduledTask) -> ScheduledTask: ...     # full-record write
    @abstractmethod
    def delete(self, task_id: str) -> None: ...                     # hard delete (rollback only)
    @abstractmethod
    def list(self, user_id: Optional[str] = None, limit: int = 50, offset: int = 0)
        -> Tuple[List[ScheduledTask], Optional[int]]: ...           # newest-updated first
    @abstractmethod
    def record_trigger(self, task_id: str, request_id: Optional[str],
                       occurred_at: str, completed: bool) -> None: ...
    @abstractmethod
    def clear(self) -> None: ...

class ScheduleStoreBuilder:
    _BUILTIN_SCHEDULE_STORES = ["in_memory", "redis", "valkey", "dynamodb"]
    @staticmethod
    def build() -> ScheduleStore: ...
    # Mirrors ThreadStoreBuilder.build() (integration/thread/store/base.py:130-189):
    # reads AKConfig.get().schedule.store, lowercases type, if/elif with require_extra
    # ("redis"/"valkey"/"aws"), dotted path -> resolve_dotted(base=ScheduleStore),
    # unknown short name -> AKConfigError naming the built-ins.
```

Backends:

- `in_memory`: `ClassVar` dict keyed by `task_id`, the thread `paginate` helper shape (`integration/thread/store/base.py:16-28`).
- `redis`/`valkey` via `_RedisLikeScheduleStore` over the shared drivers (`core/util/driver/`, `_RedisLikeDriver` subclasses): key layout `{prefix}task:{task_id}` (JSON document), index sets `{prefix}index:user:{user_id}` and `{prefix}index:all`. Default `prefix` `ak:schedule:`, default `ttl` **0** (schedules must not silently expire; unlike threads).
- `dynamodb` over `DynamoDBDriver`: one item per task, partition key `task_id` (S), no sort key. `list` scans with a filter expression (the thread-store precedent, `integration/thread/store/dynamodb.py:215,226-227`; acceptable at schedule cardinalities, documented).
- `record_trigger` is a read-modify-write. Concurrency contract: last-writer-wins is acceptable (occurrence fields are monotonic and advisory); no store-level locking is added. The manager is the only writer of non-occurrence fields.

### Configuration (`core/config.py`)

New classes, placed with the other capability configs; `AKConfig.schedule` sits beside `thread` (`core/config.py:635-638`):

```python
class _ScheduleEventBridgeConfig(BaseModel):
    group_name: Optional[str] = Field(default=None, description="EventBridge Scheduler schedule-group name")
    role_arn: Optional[str] = Field(default=None, description="Execution role ARN Scheduler assumes to send to SQS")
    queue_arn: Optional[str] = Field(default=None, description="Input queue ARN used as the schedule target")

class _ScheduleProviderConfig(BaseModel):
    type: str = Field(default="local", description="Schedule provider: local | eventbridge, or a dotted path to a ScheduleProvider subclass")
    eventbridge: Optional[_ScheduleEventBridgeConfig] = None

class _ScheduleStoreRedisConfig(_RedisConfig):
    ttl: int = Field(default=0, ...); prefix: str = Field(default="ak:schedule:", ...)
class _ScheduleStoreValkeyConfig(_ValkeyConfig):   # same overrides
class _ScheduleStoreDynamoDBConfig(_DynamoDBConfig):
    table_name: str = Field(default="ak-agent-schedules", description="... partition key 'task_id' (S)")
    ttl: int = Field(default=0, ...)

class _ScheduleStoreConfig(BaseModel):
    type: str = Field(default="in_memory", description="in_memory | redis | valkey | dynamodb, or a dotted path to a ScheduleStore subclass")
    redis/valkey/dynamodb: Optional[...] = None

class _ScheduleConfig(BaseModel):
    provider: _ScheduleProviderConfig = Field(default_factory=_ScheduleProviderConfig, ...)
    store: _ScheduleStoreConfig = Field(default_factory=_ScheduleStoreConfig, ...)
    agents: Optional[list[str]] = Field(default=None, description="Agent names the schedule tools attach to; omitted = all agents")

# on AKConfig:
schedule: Optional[_ScheduleConfig] = Field(default=None, description="Scheduling capability (provider, task store, tool scoping). Absent = disabled.")
```

- Block presence is the enablement signal (the thread pattern); defaults (`local` + `in_memory`) make a bare `schedule:` block work for local dev. Env vars: `AK_SCHEDULE__PROVIDER__TYPE`, `AK_SCHEDULE__PROVIDER__EVENTBRIDGE__GROUP_NAME` / `__ROLE_ARN` / `__QUEUE_ARN`, `AK_SCHEDULE__STORE__TYPE`, `AK_SCHEDULE__STORE__DYNAMODB__TABLE_NAME`, etc. Note the same failure mode threads have: any `AK_SCHEDULE__*` env var materializes the block and enables the capability.
- Existing YAML/env configs are unaffected (`schedule` was never a valid key; unknown keys in `config.yaml` were already rejected/ignored per `YamlBaseSettingsModified` behavior, unchanged).

### Management REST handler (`schedule/handler.py`)

`ScheduleRESTRequestHandler(AuthorisedRESTRequestHandler)` (see the auth refactor below), decorator-style routes like `ThreadRESTRequestHandler.get_router` (`integration/thread/thread_chat.py:239-289`):

- `GET /api/v1/schedules` (`list_schedules`): query `user_id`, `limit`, `cursor`. `ScheduleManager.get()` `None` → 404 `"Scheduling is not configured"` (request-time, the `ThreadRESTRequestHandler` convention :253-255). A resolved user forces `user_id` (listing-scope rule :256-258). `ValueError` → 400. Response `{"schedules": [task.model_dump(mode="json"), ...], "next_cursor": ...}`.
- `GET /api/v1/schedules/{task_id}` (`get_schedule`): `PermissionError` → 403 `"Schedule is not owned by the authorised user"` before the `None` → 404 check (ordering parity with :274-279).
- `PUT /api/v1/schedules/{task_id}` (`update_schedule`): body model `ScheduleAmendment(BaseModel)` carrying the full amendable representation: `prompt: str`, `at`/`cron`/`timezone`/`session_mode` (the `ScheduleSpec` one-of rule applies), `status: Literal["active", "paused"] = "active"`. 400 on validation/completed-task, 403 ownership, 404 missing. Returns the updated task.
- `DELETE /api/v1/schedules/{task_id}` (`delete_schedule`): `manager.cancel`; returns the cancelled task (status 200). 403/404 as above.
- No POST (creation is the chat API and the tools).
- 401 semantics come from the shared base verbatim.

Mounting:

- Explicitly, on any surface: `RESTAPI.run(handlers=[AgentRESTRequestHandler(), ScheduleRESTRequestHandler(authoriser=...)])`, or on ECS `AWSRestAPI.run(handlers=[ECSQueueRequestHandler(), ScheduleRESTRequestHandler(authoriser=...)])`.
- Pipeline single-process topology: `IOHandler.run` gains `handlers: Optional[list[RESTRequestHandler]] = None` and serves `[RequestHandler(), *handlers]` — the pipeline's own chat route always, plus whatever the app mounts, so an app exposing the management routes passes `ScheduleRESTRequestHandler(authoriser=...)` there. Nothing is mounted from config. `RESTAPI.run()`'s delegation rule is untouched (`api/http.py`, no-explicit-handlers rule); an app wanting the routes in this topology calls `IOHandler.run(handlers=[...])` directly.
- Startup fail-fast, independent of mounting: `IOHandler._validate_topology` calls `ScheduleManager.get()` whenever `config.schedule is not None`, so provider/transport incompatibility and missing provider config fail the boot rather than the first request — including for an app that only uses the agent tools.
- **Amended after review (2026-08-21):** `IOHandler.run` originally took `authoriser` and appended `ScheduleRESTRequestHandler` itself whenever the `schedule` block was present. Replaced with app-level mounting for consistency with every other optional REST surface (Slack, threads; #612 removed the equivalent auto-mount from `RESTAPI.run`), and the eager `ScheduleManager.get()` moved out of the mounting path into topology validation.

### Shared authorization refactor (`auth/`)

Preserving thread behavior exactly (requirement 8):

1. **`Authoriser` moves** from `integration/thread/authoriser.py` to a new `auth/authoriser.py` (class body verbatim, `integration/thread/authoriser.py:14-28`; docstring generalized to "resource-management routes"). `auth/__init__.py` (`:14`) adds `Authoriser` and `AuthValidatorAuthoriser` to its exports.

   The move is a **clean relocation, not a shim**: `agentkernel.auth` becomes the single import path, matching where `AuthValidator` already lives (every example and deployment doc already imports auth primitives from `agentkernel.auth`). The old module is deleted and the thread package's re-export (`integration/thread/__init__.py:12`) is dropped, so neither `agentkernel.integration.thread.Authoriser` nor `agentkernel.thread.Authoriser` resolves any more — the thread package owns threads, not shared auth primitives. `integration/thread/thread_chat.py` imports from `...auth.authoriser`. All consumers migrate in the same PR:

   | Surface | New import |
   |---|---|
   | `examples/api/thread-openai/app.py`, `examples/api/multimodal/thread-openai/app.py` | `from agentkernel.auth import Authoriser` |
   | `docs/docs/advanced/threads.md` (Authorization section) | same |
   | `skills/ak-add-capabilities/SKILL.md` (thread authoriser snippet) | same |
   | `tests/test_thread_router.py` | same |

   `docs/versioned_docs/` is a frozen release snapshot and is left untouched. This is a **breaking import change** for applications that subclass `Authoriser` off the thread path; it belongs in the phase-1 `refactor:` PR body and the release notes.
2. **`AuthValidatorAuthoriser`** (in `auth/authoriser.py`): adapter so one user-supplied `AuthValidator` serves REST global auth, WS `$connect`, threads, and schedules:

   ```python
   class AuthValidatorAuthoriser(Authoriser):
       def __init__(self, validator: AuthValidator): ...
       def authorise(self, token: str) -> Optional[str]:
           result = self._validator.validate(token)
           return result.subject if result.is_valid else None
   ```
3. **`AuthorisedRESTRequestHandler`** in `api/handler.py` (beside `RESTRequestHandler` :15): `__init__(self, authoriser: Optional[Authoriser] = None)` plus `_resolve_user(request)` moved verbatim from `ThreadRESTRequestHandler` (`integration/thread/thread_chat.py:218-237`), keeping the three tested 401 details (`"Missing authorization header"`, `"Invalid authorization header"`, `"Unauthorized"`; pinned by `ak-py/tests/test_thread_router.py:129-167`). `ThreadRESTRequestHandler` and `ScheduleRESTRequestHandler` subclass it; `ThreadRESTRequestHandler.__init__` (:210-216) drops its own `_authoriser` handling in favor of `super().__init__(authoriser)`.
4. The `PermissionError` → 403 mapping stays per-route with per-resource messages (the thread convention); no shared helper is extracted for it (two call sites, distinct details).

### Agent system tools (`schedule/tools.py`)

Five tools, sandbox conventions (`sandbox/tools.py:1-10,304-352`): all `async`, JSON-string returns, `{"error": ...}` on failure, no exceptions escape; the capability guidance blob rides `create_schedule.description`, the other four descriptions are `""` (the `if tool.description` filter, `core/tool.py:220-222`).

```python
def get_schedule_tools() -> list[SystemTool]:
    return [SystemTool(name="create_schedule", description=_GUIDANCE, func=create_schedule),
            SystemTool(name="list_schedules", description="", func=list_schedules),
            SystemTool(name="get_schedule", description="", func=get_schedule),
            SystemTool(name="update_schedule", description="", func=update_schedule),
            SystemTool(name="delete_schedule", description="", func=delete_schedule)]
```

- Signatures: `create_schedule(prompt, cron=None, at=None, timezone="UTC", session_mode="reuse", agent=None)`; `update_schedule(task_id, prompt, cron=None, at=None, timezone="UTC", session_mode="reuse", status="active")` (PUT semantics); `list_schedules()`, `get_schedule(task_id)`, `delete_schedule(task_id)`.
- Every tool starts `manager = ScheduleManager.get(); if manager is None: return _DISABLED` (`_DISABLED = json.dumps({"error": "scheduling capability is disabled"})`, the sandbox first-line pattern `sandbox/tools.py:79-81`).
- **Acting user**: `Session.current().get_volatile_cache().get(ACTING_USER_CACHE_KEY)` (imported from `core.runtime`, or equivalently from `core`, which re-exports it). Every tool requires it: absent → `{"error": "scheduling requires a user identity: include user_id on the chat request"}`. `list_schedules` is scoped to the acting user; `get`/`update`/`delete` pass it for ownership enforcement (a `PermissionError` becomes an error JSON).
- `create_schedule` with `session_mode="reuse"` uses `Session.current().id` as the originating session.
- **Registration**: one new block in `SystemToolFactory.get_all()` after the sandbox block (`core/tool.py:194-198`):

  ```python
  schedule_config = getattr(AKConfig.get(), "schedule", None)
  if schedule_config is not None and SystemToolFactory._agent_allowed(schedule_config, agent_name):
      from ..schedule.tools import get_schedule_tools
      tools.extend(get_schedule_tools())
  ```

  Attachment, prompt injection, and `agents` scoping then come free from `Agent._attach_system_tools` / `_setup_system_prompt` (`core/base.py:505-522`).

### Trigger consumption changes (the runners)

`request_id` body fallback, applied uniformly (attribute keeps precedence; injected back into attributes so output-side forwarding keeps working):

1. **Pipeline** (`pipeline/agent_runner.py`): `_require_request_id(message)` (:89-94) becomes `_resolve_request_metadata(message, body)`: read `ATTR_REQUEST_ID` from attributes, else `getattr(body, "request_id", None)` (extras are attributes under `extra="allow"`), else raise the existing `ValueError` with `"attributes"` broadened to `"attributes or body"`. When resolved from the body, `message.attributes[ATTR_REQUEST_ID] = request_id`, and `message.attributes.setdefault(ATTR_USER_ID, body.user_id)` when the body carries one, so `_send_to_output`'s attribute forwarding (:96-99) and the response handler's requirement (`pipeline/response_handler.py:121-123`) are satisfied. Both `AgentRunner.process` (:32-44) and `StreamAgentRunner.process` (:125-139) use it.
2. **ECS** (`deployment/aws/containerized/akagentrunner.py`): `_get_record_attributes(cls, raw_queue_message, body=None)` (:47-74): when the `request_id` custom attribute is absent, fall back to the parsed body (`process_message` passes the body it already validated at :102; `on_permanent_failure` (:122-130) passes `None` and the method best-effort parses `record["Body"]` itself, staying inside its own try/except). `user_id` falls back to `body.user_id` the same way. `ECSStreamAgentRunner` inherits both.
3. **Serverless** (`deployment/aws/serverless/akagentrunner.py`): the same fallback in both `_get_record_attributes` implementations (:37-57 and :181-203; the `attributes["MessageGroupId"]` direct index at :57/:201 is safe: Scheduler always sets `MessageGroupId` on FIFO sends).

**ECS status-code propagation** (design decision: 202 surfaces on every REST surface):

4. `ECSAgentRunner.process_message` (:110) stops discarding the status: `status_code, agent_response = ...`, and `_send_to_output_queue` (:77-94) gains a `status_code` custom attribute (`SQSHandler.CustomAttribute(name="status_code", value=str(status_code), ...)`). `on_permanent_failure` sends `500`.
5. `ECSOutputConsumer._construct_message_for_store` (:145-166) adds `"status_code": int(message_attributes.get("status_code") or 200)` to the stored record; the permanent-failure store path (:137-140) stores `500`.
6. `RestHandler._build_sync_response` (`pipeline/request_handler.py:64-67`) absorbs the status-honoring logic currently in `RequestHandler._build_sync_response` (:269-277), extended for 2xx: records with `status_code >= 400` raise `HTTPException(status_code, body)`; `200 < status_code < 400` returns `JSONResponse(content=body, status_code=status_code)`; else the body. The `RequestHandler` override is deleted (inherits). ECS (`ECSQueueRequestHandler`, `deployment/aws/containerized/core/api/rest_api.py:9-27`) inherits the same behavior. Records without `status_code` (pre-change rows, TTL-bound) default to 200: unchanged behavior.

### Optional dependencies (`ak-py/pyproject.toml`)

- New extra: `schedule = ["croniter>=3.0"]` (cron parsing + next-fire computation; needed by the manager's validation and the local provider).
- The EventBridge provider rides the existing `aws` extra (`boto3>=1.41.4`).

### Example

New `examples/api/schedule-openai/` (the `examples/api/thread-openai` layout): `app.py` running `IOHandler.run(handlers=[ScheduleRESTRequestHandler()])` with a `schedule:` block (local provider, in_memory store), `config.yaml`, `README.md` showing a deferred chat request (`schedule.at` / `schedule.cron`), the 202 acknowledgement, the management routes, and an agent prompt that exercises `create_schedule`.

### Terraform changes (`ak-deployment/ak-aws/`)

Containerized (`containerized/`):

- `variables.tf`: `enable_scheduling` (bool, default `false`) and `create_dynamodb_schedule_table` (bool, default `false`), styled like `create_dynamodb_thread_table` (:130-134). A root `check` block (the serverless `state.tf:368-382` style) asserts `enable_scheduling` implies `queue_mode`.
- New root `eventbridge.tf` (the file-per-concern layout): `aws_scheduler_schedule_group` (`count = var.enable_scheduling ? 1 : 0`, name `"${local.prefix}-schedules"`, `tags = var.tags`); `aws_iam_role.scheduler_execution` trusting `scheduler.amazonaws.com` (with an `aws:SourceAccount` condition) plus an inline/attached policy granting `sqs:SendMessage` on `module.queues[0].input_queue_arn`.
- `modules/queues/`: new variable `input_content_based_deduplication` (bool, default `false`) wired to the input queue's `content_based_deduplication` (`modules/queues/main.tf:17`); the root passes `var.enable_scheduling`. Output queue untouched.
- Schedule store table: raw `aws_dynamodb_table.schedule_store` beside the response store (`containerized/dynamodb.tf:4-22` pattern), `count = var.create_dynamodb_schedule_table ? 1 : 0`, name `"${local.prefix}-schedule-store"`, billing `PAY_PER_REQUEST`, hash key `task_id` (S).
- `state.tf` locals (the :14-15 pattern): `schedule_group_name/arn`, `scheduler_execution_role_arn`, `dynamodb_schedule_table_name/arn`, each null-or-value.
- IAM (the `containerized/iam.tf` policy+attachment pairs :3-38/:71-75): `rest_service_scheduler_policy` and, in `modules/agent-runner/main.tf` beside the thread policy (:163-192), `agent_runner_scheduler_policy`: `scheduler:CreateSchedule`, `scheduler:UpdateSchedule`, `scheduler:DeleteSchedule`, `scheduler:GetSchedule` scoped to `arn:aws:scheduler:*:<account>:schedule/${group}/*`, plus `iam:PassRole` scoped to the execution role ARN. DynamoDB schedule-table policy pairs mirror the thread-table ones for both roles.
- Env injection (conditional-merge maps, `modules/rest-service/main.tf:1-33`, `modules/agent-runner/main.tf:4-24`): when scheduling is enabled, `AK_SCHEDULE__PROVIDER__TYPE = "eventbridge"` is **not** injected (Terraform never sets `type`, the thread rule); injected are `AK_SCHEDULE__PROVIDER__EVENTBRIDGE__GROUP_NAME`, `__ROLE_ARN`, `__QUEUE_ARN` (input queue ARN), and, guarded on the table ARN, `AK_SCHEDULE__STORE__DYNAMODB__TABLE_NAME`. The application still declares `schedule.provider.type: eventbridge` and `schedule.store.type: dynamodb` in its committed `config.yaml`. Note (documented in the module README): with env-var materialization, the injected `AK_SCHEDULE__*` vars alone would enable the capability with the default `local`/`in_memory` backends; declaring the block in `config.yaml` is required for correct backends, exactly like `thread.type`.
- `outputs.tf`: `schedule_group_arn`, `scheduler_execution_role_arn`, `schedule_table_name`, null-safe.

Serverless (`serverless/`): the mirrored set: `enable_scheduling` + `create_dynamodb_schedule_table` variables (near `variables.tf:179-183`), schedule group + execution role + table in `state.tf` with locals (:22-23 pattern), `queue_config` gains `content_based_deduplication` forced true under `enable_scheduling` (`modules/queues/main.tf:15`), IAM pairs in `modules/request-handler/main.tf` (near :192-215) and `modules/agent-runner/main.tf` (near :174-205), env maps in both (`request-handler/main.tf:283-318`, `agent-runner/main.tf:239-260`).

Docs surfaces: root README input tables, `containerized/modules/README.md` env-var tables (:145-154, :231-240), and the serverless README input table gain the new rows.

### Behavioural changes

All intentional; each traced to a design requirement:

1. A JSON chat request carrying an unknown `schedule` key stops flowing to the agent as `AgentRequestAny` (`core/chat_service.py:118-131`). With the block configured it defers execution; without it, 400 `"Scheduling is not configured..."`. (Design: Motivation; requirement "schedule block".)
2. `scheduled_task_id` / `scheduled_time` keys likewise stop leaking as `AgentRequestAny` (they become typed fields and `known_fields` entries).
3. A deferred creation returns HTTP **202** on direct REST (via `JSONResponse`), through the pipeline waiter/poller, and on ECS; queue runners forward it as `STATUS_CODE`/`status_code`. (Design: resolved question 1.)
4. `ECSAgentRunner` stops discarding `ChatService`'s status code (:110) and forwards it; `ECSOutputConsumer` stores it. Stored ECS records gain a `status_code` key (readers unaffected: records are TTL-bound and read via `_build_sync_response`).
5. ECS REST_SYNC/REST_ASYNC replies whose stored status is >= 400 now surface as HTTP 4xx/5xx (`HTTPException`) instead of HTTP 200 with an error body: parity with direct mode and the pipeline (`RequestHandler._build_sync_response` :269-277 becomes the shared base behavior).
6. A missing `request_id` message attribute no longer permanently fails a queue message whose **body** carries `request_id` (the trigger contract); messages missing both keep today's error path (`pipeline/agent_runner.py:89-94`, `akagentrunner.py:62-64`, serverless :47-54/:191-196).
7. `IOHandler.run` takes `handlers` (mounted alongside its own `RequestHandler`): the schedule management routes are the application's to mount, like a Slack handler. It fails startup on provider/transport incompatibility whenever the `schedule` block is present, mounted or not (new `AKConfigError`, joining the existing fail-fasts `pipeline/io_handler.py:107-119`).
8. The thread handler does not create a thread or record messages for a request carrying `schedule` (checked before `ThreadRecorder.pre_run`, `thread_chat.py:120,146`).
9. Runs whose request carries `user_id` now expose it in the session volatile cache under `ak.acting_user_id` for the duration of the run (visible to hooks/tools; set and cleared by `Runtime` inside the per-session lock). `AgentHandler.run_*`, `AgentService.run_multi`/`stream_multi`, and `Runtime.run`/`stream` each gain a backward-compatible optional `acting_user_id` parameter.
10. The Terraform input queue flips to `content_based_deduplication = true` when `enable_scheduling` (containerized `modules/queues/main.tf:17`, serverless equivalent). App senders are unaffected: an explicit `MessageDeduplicationId` (always sent today, `pipeline/request_handler.py:86`, `sqs_handler.py:343-350`) takes precedence over content-based dedup.
11. `ThreadRESTRequestHandler` inherits `_resolve_user` from the new `AuthorisedRESTRequestHandler` and `Authoriser` moves to `auth/`: runtime behavior and error strings identical, but **the import path changes** — `Authoriser` is now only importable from `agentkernel.auth`, no longer from `agentkernel.thread` or `agentkernel.integration.thread`. Apps that subclass it must update one import line.

**Non-changes**: the three multipart route signatures (`api/handler.py:76-105`, `pipeline/request_handler.py:343-380`, `integration/thread/thread_chat.py:79-108`) gain no `schedule` form field, so multipart requests cannot carry a schedule block (design non-goal; the inherited model field simply stays `None` there); chat wire shapes for non-scheduled requests (200 bodies byte-identical); `ResponseBuilder.build_response` for status 200 and all error paths; messaging integrations, CLI, A2A, MCP; thread store layouts and thread routes; `RESTAPI.run()` delegation rule (`cls is RESTAPI`, no explicit handlers, `in_memory`); `QueueMessage` envelope shape; session store layouts; serverless WebSocket paths; `SQSHandler` send-side signatures; existing ECS record keys (`session_id`, `request_id`, `body`) all remain, `status_code` is additive.

## Error handling

| Failure | Surface behavior |
|---|---|
| `schedule` block present, capability unconfigured | `ValueError` → 400 on direct REST/thread handler; in queue mode the runner's `ChatService` maps it to a stored 400 → `HTTPException(400)` at the waiter/poller |
| Invalid spec: both/neither `at`/`cron` (pydantic), bad cron, unknown timezone, `at` not ISO / has UTC offset / in the past, cron with both day fields (EventBridge) | `ValueError` → 400 (chat + PUT), error JSON (tools) |
| Creation without `user_id` | `ValueError` → 400 (chat); error JSON (tools, from the acting-user check) |
| Provider create/update failure (`botocore ClientError`, local send failure at registration) | `ScheduleError` → 500 via the wrappers; create rolls the store record back (hard delete), update restores the previous record |
| Provider/transport mismatch (`eventbridge` + non-`sqs` transport) | `AKConfigError` at `ScheduleManager` construction: app-build failure when the management routes are mounted; otherwise first scheduling use → 500 |
| Missing `schedule.provider.eventbridge.{group_name,role_arn,queue_arn}` | `AKConfigError` at factory time (same surfacing as above) |
| `croniter` not installed | `ImportError` with the extra hint via `require_extra("schedule", ...)` at manager build (`core/util/factory.py:50-64`) |
| Store create/update/list failure | Propagates → 500 / error JSON |
| `record_trigger` store failure | Logged, never fails the run (`ChatService._record_trigger` and the manager both guard) |
| Ownership violation | `PermissionError` → 403 (routes), error JSON (tools) |
| Unknown `task_id` | 404 (routes), error JSON (tools) |
| Amend/cancel a `completed`/`cancelled` task | `ValueError` → 400 |
| Missing/invalid/rejected Bearer token (authoriser configured) | 401 with the three existing detail strings (shared base) |
| EventBridge `delete_schedule` on an already-deleted schedule (one-time auto-delete) | Swallowed (`ResourceNotFoundException` tolerated): cancel of a fired one-time task still records `cancelled` |
| Local provider fire-time send failure | Logged, occurrence skipped, recurring schedules stay armed |
| Trigger message missing `request_id` in both attributes and body | Unchanged existing path: retries then permanent-failure handling |

## Testing

New test files (patterns per `ak-dev-testing-conventions`: config monkeypatching via `monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: FakeCfg))`, fake drivers for redis-like stores, mocked boto3):

- `tests/test_schedule_model.py`: `ScheduleSpec` one-of validation, `session_mode` literal, `ScheduledTask` JSON round trip, amendment model.
- `tests/test_schedule_manager.py`: `get()` returns `None` without the block; transport-compatibility fail-fast (monkeypatch `QueueTransportFactory.resolve_type`); semantic validation matrix (cron/tz/at); create order + rollback on provider failure (fake provider raising); ownership `PermissionError`; amendment rules (completed → 400-shaped `ValueError`); cancel tolerates provider not-found; `record_trigger` updates occurrence fields, completes one-time tasks, and never raises (store failure injected); cursor pagination through the shared helpers.
- `tests/test_schedule_store.py`: in_memory, redis-like (fake `_RedisLikeDriver` client), and DynamoDB (mocked `DynamoDBDriver`) round trips: create/get/update/delete/list-filter/record_trigger.
- `tests/test_schedule_provider_local.py`: next-fire computation (cron + timezone, `at`), single fire for one-time, re-arm for cron, token substitution, delivery into `InMemoryTransport` with **empty attributes** (uses `InMemoryTransport.reset()` isolation), pause/delete disarm.
- `tests/test_schedule_provider_eventbridge.py`: mocked boto3 `scheduler` client asserting exact `create_schedule`/`update_schedule`/`delete_schedule` kwargs: expression translation (5→6 field, `?` day rule, `at()` form), `ScheduleExpressionTimezone`, `ActionAfterCompletion` DELETE/NONE, `State` mapping, `Input` token replacement to `<aws.scheduler.execution-id>`/`<aws.scheduler.scheduled-time>`, `SqsParameters.MessageGroupId`; `ClientError` → `ScheduleError`; delete idempotency.
- `tests/test_schedule_tools.py`: the sandbox agent-surface suite shape (`tests/test_sandbox.py:837-935`): disabled short-circuit; `SystemToolFactory.get_all` includes/excludes on block presence and `agents` scoping (including the anonymous-caller rule and independence from the sandbox `agents` list); prompt-suffix content; acting-user read from the volatile cache (set via a real `Session`); per-tool JSON contracts including the no-identity error.
- `tests/test_schedule_router.py`: mirror of `tests/test_thread_router.py`: 404 unconfigured; the three 401 variants through the shared base; listing forced to the authorised user; 403-before-404 ordering; PUT amend happy path + validation 400s; DELETE returns the cancelled task.
- `tests/test_chat_service_schedule.py` (**the riskiest consumer**: every chat surface funnels through `ChatService`): interception in all four entry points; 202 wire shape from `process_chat_request` (tuple `(202, dict)`) and `process_async_chat_request` (rest_api_mode `JSONResponse` with status 202); ack content; streaming terminal chunk (not an error chunk); 400 when unconfigured; `known_fields` non-leak for all three new keys; `_record_trigger` invoked for `scheduled_task_id` bodies and log-and-continue on store failure; acting-user cache set and cleared after the run.
- `tests/test_pipeline_agent_runner_schedule.py`: `request_id` body fallback (attribute precedence, body fallback, attribute injection for output forwarding, missing-both error), for `AgentRunner` and `StreamAgentRunner`.
- `tests/test_ecs_agent_runner_schedule.py`: ECS `_get_record_attributes` fallback (with and without a pre-parsed body), status-code custom attribute on `_send_to_output_queue`, `on_permanent_failure` resilience.
- `tests/test_ecs_output_consumer_status.py`: stored record gains `status_code` (present, absent → 200, permanent failure → 500).
- `tests/test_authoriser_shared.py`: `AuthValidatorAuthoriser` (valid → subject, invalid → None); `agentkernel.auth`'s export is the class defined in `auth/authoriser.py`; and the relocation is asserted complete — `agentkernel.integration.thread` and `agentkernel.thread` no longer expose an `Authoriser` attribute, so a re-export cannot creep back in unnoticed.

Existing tests that must pass **unchanged** (they pin behavior this change refactors around): `tests/test_thread_integration.py`, `tests/test_chat_service_core.py`, `tests/test_chat_service_streaming.py`, `tests/test_sqs_handler.py` (send-side wire shape), `tests/test_store_builders.py` (extended with `ScheduleStoreBuilder` unknown-type + BYO dotted cases), `tests/test_sandbox.py` (tool-factory independence).

`tests/test_thread_router.py` is the one exception: its **assertions** stay untouched (the 401/403 strings still pin the extracted `AuthorisedRESTRequestHandler` base), but its import line moves `Authoriser` to `agentkernel.auth`. Existing patch targets that must keep resolving: everything under `deployment/common/*` shims (untouched). Nothing patches `agentkernel.integration.thread.authoriser.Authoriser`, which is why that module could be deleted outright rather than shimmed.

Changed existing files: `tests/test_thread_integration.py` gains a "schedule block skips recording" case; `tests/test_store_builders.py` gains the schedule-store cases; a `RestHandler._build_sync_response` status-honoring case is added where the pipeline request-handler tests live.

Run: `cd ak-py && uv run pytest`, plus `make lint-check`. Terraform: `terraform fmt -check` and `terraform validate` in `ak-deployment/ak-aws/containerized` and `ak-deployment/ak-aws/serverless`.
