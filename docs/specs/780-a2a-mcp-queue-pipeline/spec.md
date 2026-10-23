# #780: A2A and MCP go through the queue, and only the queue — Implementation Spec

A2A and MCP stop running agents in the IO process. Both executors put a chat request on the input
queue and wait for its reply in the response store, the way the REST chat route already does. The
work is one new pipeline class (`QueueRequestClient`), one message attribute (`protocol`), two
rewritten executors, startup checks in three entry points, and an a2a-sdk cap. There is **no new
configuration**. The requirements come from [design.md](design.md). Every claim below was checked
against `develop` at `ddf65964`.

---

## Design amendments

Writing this spec turned up five things the design got wrong or left out. Each one is fixed in
`design.md`, and all five were approved on 2026-10-21.

| # | Design said | Code shows | Amended to |
|---|---|---|---|
| A1 | `message:stream` "returns the one whole reply" | AK cards declare `AgentCapabilities(streaming=False)` (`core/builder.py:46`), and a2a-sdk 0.3.6 refuses `message:stream` on such a card before the executor runs (`a2a/server/request_handlers/rest_handler.py:91`, `@validate(... capabilities.streaming ...)`) | `message:stream` stays refused, as it is today |
| A2 | Only **MCP** image replies change text | The old A2A path used `AgentService.run` (`core/service.py:153-158`), which also maps `AgentReplyImage` to `"Non-text reply given"`. `AgentReplyImage` is not a subclass of `AgentReplyText` (`core/model.py:127`) | Both A2A and MCP image replies change |
| A3 | Startup checks fire when "A2A or MCP" is on | MCP with `expose_agents: false` mounts only the app's own tools (`api/mcp/akmcp.py:95`) and runs no agent | The trigger is `a2a.enabled`, or `mcp.enabled` **and** `mcp.expose_agents` |
| A4 | ECS raises from `RESTAPI.run` | That `run` happens inside the `rest-api` thread (`ecs_io_handler.py:61`, `:72`), after the output-consumer thread has started | `ECSIOHandler.run` also runs the check first, before it starts any thread |
| A5 | k8s example: add extras and blocks | `uv.lock` is gitignored (`examples/k8s/openai-queue-mode/.gitignore`), so images resolve `agentkernel` from PyPI, whose `a2a` extra is uncapped. `package.sh` copies only the entry file into each image (`deploy/package.sh:56`). The chart defaults to 2 io-handler replicas (`chart/values.yaml`, `ioHandler.replicaCount: 2`). The chart smoke ignores `api/**` changes (`chart-test.yaml:11-24`) | Add a direct a2a-sdk pin, copy the shared module, set `mcp.stateless_http: true`, and widen the path filter |

---

## Design

### Files

| File | Change |
|---|---|
| `ak-py/src/agentkernel/pipeline/request_client.py` | **New**: `QueueRequestClient`, `QueuedReply`, `ReplyTimeoutError` |
| `ak-py/src/agentkernel/pipeline/__init__.py` | Lazy exports for the three new names |
| `ak-py/src/agentkernel/pipeline/envelope.py` | `ATTR_PROTOCOL = "protocol"` |
| `ak-py/src/agentkernel/pipeline/request_handler.py` | `RestHandler` borrows the client's budget and wait loop; `_DEFAULT_RESPONSE_RETRY` removed |
| `ak-py/src/agentkernel/pipeline/agent_runner.py` | Forward `protocol`; hand tagged messages to the single-reply path in the stream and realtime runners |
| `ak-py/src/agentkernel/pipeline/response_handler.py` | Check `protocol` before the mode; extract `_store_failure_record` |
| `ak-py/src/agentkernel/pipeline/io_handler.py` | Shared-store check for A2A/MCP in every mode; warn on an empty agent registry |
| `ak-py/src/agentkernel/api/http.py` | `RESTAPI.agent_protocol_surfaces`, `RESTAPI.reject_unqueued_protocols`, and the call in `run` |
| `ak-py/src/agentkernel/api/a2a/a2a.py` | Executor uses the client; `AgentService` import removed |
| `ak-py/src/agentkernel/api/mcp/akmcp.py` | Executor uses the client; `AgentService` import removed |
| `ak-py/src/agentkernel/deployment/aws/containerized/ecs_io_handler.py` | Runs the check before starting threads |
| `ak-py/pyproject.toml`, `ak-py/uv.lock` | `a2a-sdk[http-server]>=0.3.6,<1`, then re-lock |
| `examples/k8s/openai-queue-mode/**`, `.github/workflows/chart-test.yaml` | See [§7](#7-k8s-example-and-ci) |

### 1. `QueueRequestClient` (`pipeline/request_client.py`, new)

```python
class QueuedReply(BaseModel):
    """One whole reply read back from the response store."""
    request_id: str
    status_code: int = 200
    body: Any = None

    @property
    def is_error(self) -> bool: ...            # status_code >= 400
    @property
    def result(self) -> Any: ...               # body["result"] when body is a dict, else None
    @property
    def media_type(self) -> Optional[str]: ... # body.get("media_type") when body is a dict
    @property
    def error(self) -> Optional[str]: ...      # body.get("error") when body is a dict

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> "QueuedReply": ...


class ReplyTimeoutError(TimeoutError):
    """The wait budget ran out before the reply was stored."""
    def __init__(self, request_id: str, retry_count: int, delay: float): ...  # all three kept as attributes


class QueueRequestClient:
    """Puts one chat request on the input queue and waits for its whole reply in the response store."""

    DEFAULT_BUDGET: ClassVar[tuple[int, float]] = (60, 1.0)

    def __init__(
        self,
        transport: Optional[QueueTransport] = None,
        response_store: Optional[ResponseStore] = None,
        budget: Optional[tuple[int, float]] = None,
    ): ...

    async def request(self, body: BaseRunRequest, protocol: str) -> QueuedReply: ...

    @classmethod
    def budget_for(cls, response_store_config: Optional[_ResponseStoreConfig]) -> tuple[int, float]: ...

    @staticmethod
    async def wait_for_record(store: ResponseStore, request_id: str, retry_count: int, delay: float) -> Optional[dict]: ...

    @staticmethod
    def protocol_of(attributes: Mapping[str, Any]) -> Optional[str]: ...
```

**Rules**

1. **It uses only the existing plug-in points.** It holds a `QueueTransport` and a `ResponseStore`,
   so any built-in or bring-your-own backend works. When one isn't passed in, it is built on first use
   with `QueueTransportFactory.create()` or `ResponseStoreFactory.create()`. The budget comes from
   `budget_for(AKConfig.get().execution.response_store)`. Explicit constructor arguments mean config
   is never read (the #503 seam pattern). No new ABC or factory is needed: the two factories already
   resolve dotted-path BYO backends (`transport/base.py:123`, `response_store/factory.py:47-48`).
2. **The message envelope.** `request()` makes a fresh `uuid4` request id and calls
   `RequestProducer(transport).enqueue(body, request_id, attributes={ATTR_PROTOCOL: protocol})`.
   The producer sets the body to `model_dump(exclude_none=True)` (`producer.py:45`), uses the
   **session id as the group id**, and uses the **request id as the dedup id**
   (`producer.py:47-48`). The send runs in `asyncio.to_thread`, as REST does
   (`request_handler.py:139`).
3. **It validates before enqueueing** and raises `ValueError` without sending anything when:
   - `body.session_id` is empty: `"No session_id is provided in the request"`;
   - `body.prompt` is empty: `"No prompt provided in the request"`;
   - `protocol` is empty: `"protocol is required"`.

   The first two messages match `ChatService._validate` word for word (`core/chat_service.py:785`, `:788`).
4. **The wait.** `wait_for_record` is the body of `RestHandler._await_response_record`, moved as is
   (`request_handler.py:89-97`):
   - The first read happens straight after the enqueue.
   - Every read is `asyncio.to_thread(store.get_record, request_id, True)`, so the record is
     deleted when it is read.
   - It sleeps `delay` seconds between reads, and not after the last one.
   - It returns the record, or `None` once the budget is spent. The longest wait is
     `(retry_count - 1) * delay`.
5. **The budget.** `budget_for(None)` returns `DEFAULT_BUDGET`, which is 60 reads 1 s apart, about
   59 s. Otherwise it returns `(retry_count, delay)` from the block (`core/config.py:514-515`); at
   the block defaults that is 5 reads 5 s apart, about 20 s. The 60 × 1 default **moves** here from
   `request_handler.py:22`; it is not copied.
6. **The timeout.** When `wait_for_record` returns `None`, `request()` raises
   `ReplyTimeoutError(request_id, retry_count, delay)`. A reply that arrives later stays in the
   store until the backend's TTL removes it. The in-memory store keeps it until the process exits
   (`response_store/in_memory.py:18-20`). REST's 504 leaves the same leftover today.
7. **The reply.** `QueuedReply.from_record` reads `status_code` as
   `int(record.get("status_code") or 200)`, the same missing-status rule REST uses
   (`request_handler.py:117`), and keeps `record["body"]` as is.
8. **Errors.** An exception from the transport or the store reaches the caller unchanged. Only a
   spent budget becomes `ReplyTimeoutError`. A reply with status ≥ 400 is returned, not raised; the
   caller checks `is_error`.
9. **Concurrency.** Each surface uses one client for every request it is handling at once, all on
   the server's event loop.
   - Lazy construction happens on the event-loop thread, before the first `to_thread` hand-off, so
     two requests cannot both build one.
   - `QueueTransport.send` must already be safe to call from any thread (`transport/base.py:10`).
   - Stores are already shared across worker threads in exactly this way by `RestHandler`
     (`request_handler.py:45-47`).
10. **Cost per request.** One send plus at most `retry_count` store reads, each on the default
    executor. That is the same as a REST_SYNC request today.
11. **`protocol_of(attributes)`** returns the `protocol` value only when it is a non-empty `str`,
    and `None` otherwise. This is the same rule as `IntegrationDelivery.integration_of`
    (`integration_delivery.py:33-41`), and it lives on the class that owns the "someone is waiting
    on the store" contract. Runners and the response handler call it; nothing else reads
    `ATTR_PROTOCOL` directly.
12. **Exports.** `QueueRequestClient`, `QueuedReply` and `ReplyTimeoutError` join
    `pipeline/__init__.py`'s `_LAZY_EXPORTS` and its `TYPE_CHECKING` mirror. The module imports
    only `core` and `pipeline` modules, and never FastAPI.

**REST borrows the loop** (`pipeline/request_handler.py`)

- Delete `_DEFAULT_RESPONSE_RETRY` (`:19-22`).
- `RestHandler._response_retry_config()` returns
  `QueueRequestClient.budget_for(self._config.execution.response_store)`.
- `RestHandler._await_response_record(request_id)` returns
  `await QueueRequestClient.wait_for_record(self.get_response_store(), request_id, *self._response_retry_config())`.
- Not changed: `get_transport`, `get_response_store`, `_enqueue_request` (which
  `ThreadRequestHandler` overrides at `integration/thread/thread_chat.py:258`), `_effective_mode`,
  `_build_sync_response`, the 504 detail, and every route. REST does **not** stamp `protocol`; its
  replies keep using mode routing.

### 2. The `protocol` attribute

- `pipeline/envelope.py` adds `ATTR_PROTOCOL = "protocol"`, commented as: *a caller is waiting for
  one whole reply in the response store; deliver it there whatever `execution.mode` is.*
- The values are `A2A.PROTOCOL = "a2a"` and `MCP.PROTOCOL = "mcp"`. Only whether the attribute is
  present matters for routing; the value shows up in logs. The name avoids the `reply_` prefix,
  which already means integration reply context (`envelope.py:20`).

| Component | Today | After |
|---|---|---|
| `_FORWARDED_ATTRIBUTES` (`agent_runner.py:21`) | `request_id`, `user_id`, `endpoint_url` | adds `protocol` |
| `StreamAgentRunner.process` (`:216-218`) | integration → `AgentRunner.process` | integration **or** protocol → `AgentRunner.process` |
| `StreamAgentRunner.on_permanent_failure` (`:246-248`) | integration → base | integration **or** protocol → base (500 error body) |
| `RealtimeAgentRunner.process` (`:270-274`) | always the realtime pool | protocol → `AgentRunner.process`; otherwise the pool |
| `RealtimeAgentRunner.on_permanent_failure` (`:276-286`) | pool failure chunk | protocol → `AgentRunner.on_permanent_failure`; otherwise unchanged |
| `ResponseHandler.process` (`:59-84`) | integration, then mode | integration, then **protocol → `_store_response`**, then mode |
| `ResponseHandler.on_permanent_failure` (`:86-134`) | integration, then mode | integration, then **protocol → 500 record**, then mode |

**Rules**

1. Integration is checked first. A message carrying both attributes counts as integration traffic.
   No built-in producer sets both.
2. A tagged message in the stream runner hands off *before* the `USER_ID` check (`:223`). A tagged
   request over a broker therefore needs no user id.
3. The REST-mode 500-record block (`response_handler.py:125-132`) becomes
   `_store_failure_record(message, request_id, error_text)`. The protocol branch and the REST-mode
   branch both call it, and both keep the "request_id missing" warning (`:125-127`).
4. `_store_response` keeps raising on a missing `request_id` (`:219-220`). The consumer loop retries
   the message, then hands it to `on_permanent_failure`.
5. REALTIME already ends up in `_store_response` for a message that is neither integration traffic
   nor in a branched mode (only STREAM and ASYNC branch, `:72-83`). The protocol branch makes that
   explicit and independent of the mode.
6. A message without the attribute takes exactly the code path it takes today.
7. The runners import `QueueRequestClient` from the same package (`pipeline` → `pipeline`), which
   is allowed.

### 3. A2A executor (`api/a2a/a2a.py`)

```python
class A2A:
    PROTOCOL = "a2a"
    _client: Optional["QueueRequestClient"] = None

    @classmethod
    def get_client(cls) -> "QueueRequestClient":
        """The surface's one client. Imported here: api imports pipeline lazily."""

    class Executor(AgentExecutor):
        ERROR_MESSAGE = "Sorry, Agent Kernel encountered an error while processing your request"  # today's text, a2a.py:51
        TIMEOUT_MESSAGE = "Timed out waiting for the agent's reply"

        async def execute(self, context: RequestContext, event_queue: EventQueue) -> None: ...
        async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None: ...  # unchanged

        @staticmethod
        def _as_text(result: Any) -> str: ...  # a str passes through; a dict or list goes through json.dumps
```

`execute` first runs the same three checks it runs today (`a2a.py:43-46`). It then builds
`BaseRunRequest(prompt=context.get_user_input(), agent=self.agent_name, session_id=context.context_id)`
and calls `A2A.get_client().request(body, protocol=A2A.PROTOCOL)`.

| Outcome | Event enqueued | Then |
|---|---|---|
| 2xx, `result` is a `str` (text, image, unlabelled structured, paused) | `new_agent_text_message(result, context_id, task_id)` | return |
| 2xx, `result` is a dict or list (labelled structured) | `new_agent_text_message(json.dumps(result), ...)` | return |
| 2xx, `result` is missing | `ERROR_MESSAGE` | `ServerError(error=InternalError())` |
| `is_error` | `ERROR_MESSAGE` | `ServerError(error=InternalError())` |
| `ReplyTimeoutError` | `ERROR_MESSAGE` | `ServerError(error=InternalError(message=TIMEOUT_MESSAGE))` |
| Any other exception (validation, transport, store) | `ERROR_MESSAGE` | `ServerError(error=InternalError())` |

**Rules**

- `json.dumps(result)` gives the same text as the old `str(AgentReplyAny)`
  (`core/model.py:243-244`). `result` is the content that `PayloadCodec.normalise` produced
  (`core/chat_service.py:368`), and content was already normalised when it was built.
- Logs get the status, `reply.error`, the request id and the traceback. The caller never sees them.
  `InternalError(message=...)` exists in a2a-sdk 0.3.6 (`a2a/types.py:493-510`).
- Removed: `_execute_agent` (`:60-63`) and the `AgentService` import (`:12`). `Agent` stays,
  because `_build` uses it.
- Not changed: `_build`, `get_executor`, `get_cards`, `get_card`, `get_agent_names`,
  `get_task_store`, `RedisTaskStore`, and `handler.py`.

### 4. MCP executor (`api/mcp/akmcp.py`)

```python
class MCP:
    PROTOCOL = "mcp"
    _client: Optional["QueueRequestClient"] = None

    @classmethod
    def get_client(cls) -> "QueueRequestClient": ...  # same lazy pattern as A2A

    class Executor:
        ERROR_MESSAGE = "The agent could not process the request"
        TIMEOUT_MESSAGE = "Timed out waiting for the agent's reply"

        async def execute(self, session_id: str, prompt: str, ctx: Context) -> Any: ...  # same signature, so same tool schema
```

`execute` keeps its `ctx.info` line (`akmcp.py:63`). It then builds
`BaseRunRequest(prompt=prompt, agent=self.agent_name, session_id=session_id)`, calls
`MCP.get_client().request(body, protocol=MCP.PROTOCOL)`, and on success sends
`ctx.debug(f"Agent response '{reply.result}'")`.

| Outcome | Returned or raised |
|---|---|
| 2xx, `media_type` set, `result` is a dict | `ToolResult(structured_content=result, meta={"media_type": ...})` |
| 2xx, `media_type` set, `result` is a list | `ToolResult(structured_content={"result": result}, meta={"media_type": ..., "fastmcp": {"wrap_result": True}})` |
| 2xx, no `media_type` | `result`, a `str` |
| 2xx, `result` is missing | `ToolError(ERROR_MESSAGE)` |
| `is_error` | `ToolError(ERROR_MESSAGE)` |
| `ReplyTimeoutError` | `ToolError(TIMEOUT_MESSAGE)` |
| Any other exception | `ToolError(ERROR_MESSAGE)` |

**Rules**

- The two `ToolResult` branches are today's code (`akmcp.py:67-72`), now reading from `reply`.
- `ToolError` is `fastmcp.exceptions.ToolError` (present in fastmcp-slim 3.4.7, which the locked
  `fastmcp` 3.4.7 depends on).
- Details go to the `ak.mcp.executor.<agent>` log only.
- Removed: the `AgentService` and `AgentReplyText` imports. `AgentReplyAny` and `AgentRequestText`
  stop being needed too; the import list shrinks to what the module uses.
- Not changed: `get`, `get_http_app` and `_build`. App tools added through `MCP.get()` still run in
  the IO process.

### 5. Startup checks

**`RESTAPI`** (`api/http.py`)

```python
@staticmethod
def agent_protocol_surfaces(config: Optional[AKConfig] = None) -> list[str]:
    """['A2A'] when a2a.enabled, plus ['MCP'] when mcp.enabled and mcp.expose_agents (amendment A3)."""

@classmethod
def reject_unqueued_protocols(cls) -> None:
    """Raise AKConfigError when agent_protocol_surfaces() is non-empty. The message names the
    surfaces and says to use IOHandler.run(handlers=[...]), or a plain RESTAPI.run() on the
    in_memory transport."""
```

`RESTAPI.run` calls `cls.reject_unqueued_protocols()` right after
`cls._reject_pipeline_only_handlers(handlers)` (`api/http.py:109`). That is past the
`cls is RESTAPI` hand-off at `:99-106`, so subclasses are covered too. `build_app` is unchanged.
`IOHandler` serves it at `io_handler.py:120`, and its mounts at `:151-161` stay as they are.
`WebSocketGateway` builds its own app (`pipeline/ws/gateway.py:56`, `:71`) and never mounts A2A or
MCP; that is unchanged.

| Entry point | Path through the code | Result |
|---|---|---|
| `RESTAPI.run()`, no queue block (laptop, GCP `CloudRun.run()` at `deployment/gcp/akcloudrun.py:77`, direct-mode ECS such as `examples/aws-containerized/mcp/multi`) | hands off to `IOHandler.run()` at `:106` | ✅ in-memory queue |
| `IOHandler.run(...)`, any transport | `build_app` | ✅ queue |
| `RESTAPI.run(handlers=[...])` | `reject_unqueued_protocols` | ❌ `AKConfigError` |
| `RESTAPI.run()` on SQS, Kafka or NATS | `reject_unqueued_protocols` | ❌ `AKConfigError` |
| `AWSRestAPI.run(...)`, `AWSWebsocketAPI.run(...)` (`websocket_api.py:520` calls `super().run`) | `reject_unqueued_protocols` | ❌ `AKConfigError` |
| `ECSIOHandler.run(...)` | first statement: `RESTAPI.reject_unqueued_protocols()` | ❌ `AKConfigError`, before any thread |
| Lambda, Azure Functions | never mount A2A or MCP | unchanged |

**`IOHandler`** (`pipeline/io_handler.py`)

1. **`_validate_topology` adds a final check.** When the transport is not `in_memory` and
   `RESTAPI.agent_protocol_surfaces(config)` is non-empty, `execution.response_store` must be set
   with a `type` other than `None` or `in_memory`, **in every mode**. If not, it raises
   `AKConfigError` naming the surfaces. This uses the same test as `:239-244`, so a dotted-path BYO
   store passes. In REST modes the existing check fires first with its own message. RESTAPI is
   imported locally, as at `:100`.
2. **New `_warn_if_no_agents(config)`.** It runs straight after `_validate_topology`. When
   `agent_protocol_surfaces(config)` is non-empty and `Runtime.current().agents()` is empty, it
   logs one warning and startup carries on. The warning:
   - says the A2A catalog and MCP agent tool list will be empty, and that per-agent A2A routes are
     not mounted, so they return 404;
   - gives the fix: import the same agent modules in this process as in the agent runner, because
     cards and tools are built from this process's registry (`a2a.py:71-78`, `akmcp.py:96-107`).
3. The well-known card route answers an unknown name with the `AttributeError` it raises today
   (`api/a2a/handler.py:70-73`). That is not fixed here.

### 6. a2a-sdk cap

- `ak-py/pyproject.toml:185` becomes `"a2a-sdk[http-server]>=0.3.6,<1",`. Then run `uv lock` in
  `ak-py`. `agentkernel` is the only locked package that depends on `a2a-sdk` (`ak-py/uv.lock:71`),
  so the cap cannot conflict with anything.
- The code targets the 0.3.x API: `new_agent_text_message(text, context_id, task_id)`
  (`a2a/utils/message.py:19-23`), `ServerError`, `InternalError(message=...)`, and `RESTAdapter` at
  `a2a.server.apps.rest.rest_adapter`.
- #762 removes the cap.

### 7. k8s example and CI

**`examples/k8s/openai-queue-mode`**

- **New `app_agents.py`.** It holds the three agents and the `OpenAIModule([...])` call, moved from
  `app_agent_runner.py:16-38`. It does **not** set the OpenAI key. It must not be called
  `agents.py`, which would shadow the openai-agents `agents` package it imports.
- `app_agent_runner.py` imports `app_agents`, and keeps `set_default_openai_key(...)` and
  `AgentRunner.run()`.
- `app_io_handler.py` imports `app_agents`. Its docstring changes from "no modules are registered
  here" (`:3-6`) to say why they are: cards and tools are built from them.
- `deploy/package.sh` copies `app_agents.py` into the io-handler and agent-runner images.
  `create_deployment_package` takes extra files after the entry file (today it copies only
  `$entry`, `:56`).
- `pyproject.toml` adds the `a2a` and `mcp` extras to `agentkernel[...]`, plus
  `"a2a-sdk[http-server]>=0.3.6,<1"`, with a comment that #762 removes it.
- `build.sh` adds `a2a,mcp` to the local reinstall's extras (`build.sh:18`).
- `config.nats.yaml` and `config.kafka.yaml` add:

  ```yaml
  a2a:
    enabled: true
    agents: ["triage"]
  mcp:
    enabled: true
    expose_agents: true
    agents: ["triage"]
    stateless_http: true   # the chart runs 2 io-handler replicas outside dev; a stateful MCP session is pinned to one
  ```

  `a2a.url` keeps its default, `http://localhost:8000/a2a`, which matches the README's
  `port-forward 8000:80` (`README.md:77`).
- **New `protocol_client.py`**, in the style of `ws_client.py`. It is run as
  `uv run python protocol_client.py [base_url]`, defaulting to `http://localhost:8000`:
  - **A2A:** one `message:send` to `triage` through `BaseClient` with
    `RestTransport(httpx_client, card, url=f"{base}/a2a/triage")`. The explicit `url` overrides
    the card's (`a2a/client/transports/rest.py:48-51`), so a port-forward on any port works.
  - **MCP:** one `call_tool("triage", {"prompt": ..., "session_id": ...})` through
    `fastmcp.Client(f"{base}/mcp/")`.
  - It prints both replies and exits non-zero when either is empty or is an error.
- README gains an "A2A and MCP" section: both run through the queue, the agents are loaded in both
  processes, replies take at least about 1 s, and how to run `protocol_client.py`.

**`.github/workflows/chart-test.yaml`**

- Add `'ak-py/src/agentkernel/api/**'` to both `paths` lists (`:11-24`).
- New `kind-smoke` step after "Chat request through NATS" (`:217-230`), called
  "A2A and MCP requests through NATS":
  - port-forward `service/ak-agent-kernel-io 18000:80`, as the chat step does;
  - then, in `examples/k8s/openai-queue-mode`, run
    `uv run --no-sync python protocol_client.py http://localhost:18000`.
  - `--no-sync` keeps the local wheel that the "Build example images" step installed.
- It runs on all three flavors, because the baremetal and EKS overlays use the same example images
  (`ak-deployment/ak-k8s/ci/{baremetal,eks}-smoke-values.yaml`). The job-level fork guard (`:139`)
  covers it.
- "Diagnostics on failure" needs no change: it already prints the io and agent-runner
  Deployments' logs (`:232-241`).

### Consumer changes

| Consumer | Deleted | Changed | Checked unchanged |
|---|---|---|---|
| `A2A.Executor` | `_execute_agent`, `AgentService` import | `execute` | `cancel`, card building, `handler.py` routes |
| `MCP.Executor` | `AgentService`/reply-type imports | `execute` | tool name, description, argument schema, `get_http_app` |
| `RestHandler` | `_DEFAULT_RESPONSE_RETRY` | `_response_retry_config`, `_await_response_record` bodies | every route, `_enqueue_request`, 504/400/500 shapes |
| `RequestHandler`, `ThreadRequestHandler`, `ECSQueueRequestHandler` | none | none (they inherit the two bodies above) | all |
| `AgentRunner` | none | `_FORWARDED_ATTRIBUTES` | `process`, `on_permanent_failure`, thread recording |
| `StreamAgentRunner`, `RealtimeAgentRunner` | none | the hand-off guards | untagged streaming and realtime paths |
| `ResponseHandler` | none | `process`, `on_permanent_failure`, plus the extracted `_store_failure_record` | the integration, realtime, chunk and broadcast paths |
| `IOHandler` | none | `_validate_topology`, `run` (one call) | topology, threads, signals |
| `RESTAPI` | none | `run` (one call), two new methods | `build_app`, `_create_app`, auth |
| `ECSIOHandler` | none | `run` (first statement) | everything else |
| ECS runners, serverless runners and routers | none | none | all (ECS support is a follow-up, decision 2) |

### Config changes

**None.** No field is added, renamed or re-defaulted. The design's
[Configuration table](design.md#configuration-nothing-new-) lists what is reused. Existing YAML
files and `AK_*` variables load unchanged.

- `execution.mode` is ignored by A2A and MCP, because the `protocol` branch comes before it.
- `execution.response_store.{retry_count, delay}` now also set the A2A and MCP wait. Their
  descriptions (`core/config.py:514-515`) still hold, because they describe store reads.
- What *starts* is the one thing that changes: some configurations now fail at startup (see
  [Behavioural changes](#behavioural-changes) 3 and 4).

### Behavioural changes

All intentional; the reason is given for each.

1. **A2A and MCP agent calls run on the runner, never in the IO process.** This is the point of
   the issue.
2. **Replies arrive on a poll.** The first read is immediate, then one every `delay` seconds: 1 s
   with no `response_store` block, 5 s at the block defaults. The wait ends after about 59 s, or
   about 20 s at the block defaults. Before, a direct call took milliseconds and had no time
   limit. Decision 3 accepts the floor; the follow-up issue lowers it for every surface.
3. **Some entry points now fail at startup** when A2A, or agent-exposing MCP, is on:
   `RESTAPI.run(handlers=[...])`, `RESTAPI.run()` on a broker, `AWSRestAPI`, `AWSWebsocketAPI` and
   `ECSIOHandler`. The shortcut is removed, not deprecated (design non-goal 1).
4. **IOHandler on a broker needs a shared response store whenever A2A or agent MCP is on.** This
   is new for ASYNC, STREAM and REALTIME, because those replies wait in the store.
5. **IOHandler warns when the agent registry is empty** and A2A or agent MCP is on (decision 4).
6. **Empty prompts and missing sessions fail before anything is enqueued.** A2A answers with the
   generic message and `InternalError`; MCP raises `ToolError`. Before, A2A ran the agent with an
   empty prompt (`a2a.py:48` passes `get_user_input()` straight through). A runner without the
   named agent now answers 400, which the caller sees as the generic error.
7. **Image replies change text on both surfaces**, from `"Non-text reply given"` to
   `"<response>. Image <name> is attached."` (`core/model.py:139-140` via
   `core/chat_service.py:371`; amendment A2). The runner's response body is now the only source of
   reply text.
8. **MCP failures show a fixed message.** Before, an exception from the agent reached the client
   as raw text, because fastmcp only masks error details when asked to. The fixed message is safer.
9. **An A2A timeout carries a fixed message.** It arrives as the `InternalError` message; other
   failures keep the SDK's default message.
10. **The queue now serializes each conversation.** One session id is one queue group, whether the
    request came in by REST, A2A or MCP. Before, A2A and MCP calls were ordered only by the session
    lock.
11. **On a rolling upgrade in a WebSocket mode, upgrade the runners first.** An old runner does not
    forward `protocol`. The new response handler would then route the reply by mode to a WebSocket
    push that has no user id, and the A2A or MCP caller times out. REST modes are not affected,
    because they store the reply anyway.
12. **The a2a-sdk cap downgrades 1.x installs to 0.3.x.** 1.x cannot import the server today
    (trap 2).

**Non-changes**

- REST routes, request shapes and response shapes; `RequestProducer`'s envelope; untagged message
  routing.
- Response store records keep the shape `{session_id, request_id, status_code, body}`. Messages
  written before the change carry no `protocol` attribute and behave exactly as before. A store
  written by an old process is read back the same by a new one.
- A2A replies stay `Message`s; the task store, `cancel` and `message:stream` (refused, amendment
  A1) are unchanged.
- The MCP tool schema stays `(session_id, prompt)`; `ctx.info` is unchanged.
- Model failures still come back as normal 200 text replies, because the runners catch them.
- No thread recording, no scheduling and no acting user for A2A or MCP, as before.
- `ResponseStore.get_record_with_retry`'s 5 × 5 fallback (`response_store/base.py:112-122`) is
  untouched. It serves the serverless poll path, not this one.
- Public exports: `agentkernel.mcp.MCP`, `agentkernel.api` and `agentkernel.pipeline`'s existing
  names are unchanged; the pipeline only gains three names.

---

## Error handling

| Failure | Where it is detected | What the caller sees | What the logs get |
|---|---|---|---|
| A2A or agent MCP on a non-queue entry point | `RESTAPI.run` or `ECSIOHandler.run` | the process exits with `AKConfigError` | the error message |
| Broker + A2A/MCP + no shared store | `IOHandler._validate_topology` | the process exits with `AKConfigError` | the error message |
| Empty agent registry in the IO process | `IOHandler._warn_if_no_agents` | empty catalog; agent routes return 404 | one warning |
| Empty prompt or session | `QueueRequestClient.request` (nothing is sent) | A2A: generic message + `InternalError`; MCP: `ToolError` | the `ValueError` |
| Transport send fails | `request()` → the executor's `except Exception` | the generic error | the exception and traceback |
| Store read fails | `wait_for_record` → the executor | the generic error | the exception and traceback |
| Agent run fails inside ChatService (400/500) | the runner stores an error record | the generic error | the status and `reply.error` |
| Runner gives up after `max_receive_count` | `AgentRunner.on_permanent_failure` sends a 500 | the generic error | the runner's error log |
| Output message gives up | `ResponseHandler.on_permanent_failure` writes a 500 record | the generic error | the response handler's error log |
| No reply within the budget | `ReplyTimeoutError` | A2A: `InternalError(TIMEOUT_MESSAGE)`; MCP: `ToolError(TIMEOUT_MESSAGE)` | request id and budget |
| `a2a` or `mcp` extra missing | `build_app`'s lazy imports (`api/http.py:152`, `:157`) | the process exits with `ImportError`, as today | unchanged |
| No `response_store` block on `in_memory` | `ResponseStoreFactory.create` returns `InMemoryResponseStore` (`factory.py:50-59`) | works | none |

---

## Testing

The suite runs with `cd ak-py && uv run pytest`. CI installs every extra except crewai
(`ak-py/build.sh`), so a2a-sdk 0.3.x and fastmcp are present once the cap is locked.

**New test files**

| File | What it asserts |
|---|---|
| `tests/test_pipeline_request_client.py` | Message envelope: attributes `{request_id, protocol}`, `group_id == session_id`, `dedup_id == request_id`, body is `model_dump(exclude_none=True)`. `budget_for(None) == (60, 1.0)`, and the block's values when one is set. Exactly `retry_count` reads and `retry_count - 1` sleeps, the first read before any sleep (patch `agentkernel.pipeline.request_client.asyncio.sleep`). `ReplyTimeoutError` carries the request id and budget. Reads pass `get_and_delete=True`. `QueuedReply.from_record`: missing status → 200, `is_error` at 400, and `result`/`media_type`/`error` for dict and non-dict bodies. `protocol_of` accepts only a non-empty `str`. Empty session, prompt or protocol raises `ValueError` with nothing sent. Transport and store are built through the factories only when not injected. |
| `tests/test_pipeline_protocol_routing.py` | `AgentRunner` forwards `protocol` and `STATUS_CODE`. `StreamAgentRunner` turns a tagged message into **one** output message with a status (no chunks), even with `resolve_type` patched to `"nats"` and no `USER_ID`. `RealtimeAgentRunner` sends a tagged message down the single-reply path and never calls `RealtimeConnectionPool.dispatch` (patch `RealtimeConnectionPool.initialize`). Tagged permanent failures on both runners give a 500 error body. `ResponseHandler` stores a tagged message as a record in all five modes. A tagged output permanent failure stores a 500 record in all five modes. A message carrying both `integration` and `protocol` is delivered as integration traffic. An untagged STREAM/ASYNC message still broadcasts. |
| `tests/test_api_a2a.py` | Every row of the [A2A outcome table](#3-a2a-executor-apia2aa2apy), using a fake client set on `A2A._client` and a real `EventQueue` and `RequestContext`. The body sent is `prompt=get_user_input()`, `agent=<executor's agent>`, `session_id=context_id`, `protocol="a2a"`. The three existing `ValueError` checks still fire. `get_client()` builds once and reuses. Importing `agentkernel.api.a2a.a2a` leaves `agentkernel.pipeline.request_client` out of `sys.modules` (the `test_aws_lazy_exports.py` pattern). An autouse fixture saves and restores `A2A._cards`, `_executors`, `_built` and `_client`. |
| `tests/test_protocol_pipeline_roundtrip.py` | End to end on `InMemoryTransport` + `InMemoryResponseStore`, with `AKConfig._reset()` and both `reset()`s per test (the `test_integration_roundtrip.py` fixture). A pump thread named `agent-runner-pump` drains INPUT through `AgentRunner.process` and OUTPUT through `ResponseHandler.process`. A `DummyRunner` records `threading.current_thread().name` and a per-session counter in `nv_cache`. **A2A:** `RESTAPI.build_app(handlers=[])` with `a2a.enabled`, called through `BaseClient` + `RestTransport` over `httpx.ASGITransport`; `message:send` returns the agent's text. **MCP:** `fastmcp.Client(MCP.get())` with `expose_agents`; `call_tool` returns the text. Both assert that the agent ran on the pump thread, and that the same session id sent twice reaches the same session (counter 2). One case runs in `stream` mode through `StreamAgentRunner` and still gets the whole reply. |

**Changed test files**

| File | Change |
|---|---|
| `tests/test_api_mcp.py` | `TestExecutorReplyShapes` stops patching `agentkernel.api.mcp.akmcp.AgentService`. It sets `MCP._client` to a fake whose `request` returns `QueuedReply(body=ResponseBuilder.build_response(200, "s1", False, result=reply)[1])`, which is the body a runner really produces. `reset_mcp_state` also saves and restores `MCP._client`. The image test (`:183-195`) now expects `"here it is. Image chart.png is attached."`. New cases: an error status, a timeout, an exception and a missing result each raise `ToolError` with the fixed message; the body sent and `protocol="mcp"`; the module no longer has `AgentService`. |
| `tests/test_cross_surface_parity.py` | `:101-136` uses the same fake-client injection with a `ResponseBuilder`-built body, so the MCP parity runs over the exact bytes the queue carries. The docstring's A2A sentence (`:11-12`) changes: A2A still sits out because it carries the payload as JSON text rather than a data part, until #762. The reason is no longer that the import fails. |
| `tests/test_api_http.py` | New class `TestUnqueuedProtocolRefusal`. Each case raises `AKConfigError`: `RESTAPI.run(handlers=[...])` with A2A on; the same with MCP + `expose_agents`; `RESTAPI.run()` with `resolve_type` patched to `"sqs"`; a `RESTAPI` subclass. MCP without `expose_agents` serves (patch `agentkernel.api.http.uvicorn`). `RESTAPI.run()` on `in_memory` with A2A on still hands off to `IOHandler.run`. A table test covers `agent_protocol_surfaces`. Config is patched as the file does now (`agentkernel.api.http.AKConfig`). |
| `tests/test_pipeline_io_handler.py` | `_cfg` gains `a2a`/`mcp` flags. Broker + A2A + no or `in_memory` store raises in `async`, `stream`, `realtime` and `rest_sync`. A shared store passes in every mode. `in_memory` passes. An empty registry logs the warning (caplog) and `run` proceeds; a non-empty registry and MCP without `expose_agents` log nothing. |
| `tests/test_ecs_io_handler.py` | With A2A on, `ECSIOHandler.run` raises `AKConfigError`, and the stubbed `ThreadRunner.run` (`_stub_thread_runner`, `:15-19`) is never called. |
| `tests/test_pipeline_request_handler.py` | `_response_retry_config()` returns `(60, 1.0)` with no block and the block's values when set. `_await_response_record` hands the handler's own `get_response_store()` and `_response_retry_config()` to `QueueRequestClient.wait_for_record`, so a subclass override is still honoured. The existing cases run unchanged. |

**Coverage of the riskiest consumer.** `ResponseHandler` and the two runner subclasses change shape
the most. `test_pipeline_protocol_routing.py` covers every branch they gain, and the existing
`test_pipeline_response_handler.py` / `test_pipeline_agent_runner.py` suites must pass without
edits, which proves untagged traffic did not move.

**Live checks**

- CI: the chart-test kind smoke on all three flavors (§7).
- Weekly: `examples/aws-containerized/mcp/multi`'s `mcp_test.py`, unchanged, now running through the
  in-memory queue.
