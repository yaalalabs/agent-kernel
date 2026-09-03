# #524: Pluggable request/response adapter for messaging integrations — Implementation Spec

Builds the `integration/adapter/` seam that `design.md` specifies: two ABCs (`InboundAdapter`,
`OutboundAdapter`) plus a normalized `InboundRequest` envelope, hosted by a generic
`WebhookRESTRequestHandler` (webhook platforms) and a `PollerRunner` (Gmail), producing into the
`agentkernel.pipeline` input queue and delivered from the Response Handler's new integration
dispatch branch. The seven `Agent<Platform>RequestHandler` classes and their `<platform>_chat.py`
modules are deleted; each `integration/<platform>/` gains an `adapter.py` holding the platform's
inbound/outbound pair. `design.md` is the requirements source; every section below traces back to
one of its numbered requirement sections.

§10 covers design §15: the AG-UI surface on the same pipeline seam. It is not an adapter — AG-UI is
a caller-waits surface, so it uses the pipeline's producer/queue/runner plus the **response store**
as its return path, and needs three things §1–§9 did not: chunk streaming on the shared response
stores, a marker that makes the runner stream regardless of `execution.mode`, and a queue-mode
sibling handler that keeps the SSE socket while the run travels.

Two requirements were revised while writing this spec and are marked for re-review in `design.md`
(§1 `parse`'s return type, §11 where the pipeline fail-fast is raised); both are reflected here.
Two more were revised while writing §10 and are reflected in `design.md` §15.7: the session-store
check became a construction-time fail-fast rather than a documentation note, and the state snapshot
moved from the edge to the runner (design Q18) once `SessionStore.load`'s process-local cache made
an edge-side comparison unable to detect a change.

---

## Design

### 1. The adapter package — `ak-py/src/agentkernel/integration/adapter/`

```
integration/adapter/
├── __init__.py      # exports the ABCs, the envelope, the factory, the hosts
├── base.py          # Source, InboundRequest, InboundParseResult, InboundAdapter,
│                    #   PollingInboundAdapter, OutboundAdapter
├── factory.py       # IntegrationAdapterFactory
├── producer.py      # IntegrationProducer (edge → input queue)
├── webhook.py       # WebhookRESTRequestHandler
├── poller.py        # PollerRunner
├── meta.py          # shared Meta webhook auth + Send API (WhatsApp/Messenger/Instagram)
└── testing.py       # IntegrationAdapterContract
```

`design.md` §1 names `base.py` and `factory.py`; the other four modules are the hosting and
producing pieces §4, §7 and §12 require, split one concern per module rather than piled into
`base.py`.

#### `base.py`

```python
class Source(StrEnum):
    """How an inbound adapter is hosted (design §1)."""
    WEBHOOK = "webhook"
    POLLER = "poller"


class InboundRequest(BaseModel):
    """One normalized platform message, resolved at the edge (design §1)."""

    session_id: str                       # doubles as the queue group_id (per-conversation FIFO)
    request_id: str                       # the platform's own id where one exists; doubles as dedup_id
    requests: List[AgentRequest]          # prebuilt list, passed to ChatService as requests=
    prompt: str = ""
    agent: Optional[str] = None
    user_id: Optional[str] = None
    group_id: Optional[str] = None
    reply_context: Dict[str, str] = Field(default_factory=dict)


@dataclass
class InboundParseResult:
    """What one platform delivery parsed into (design §1, revised).

    ``requests`` is a list because a single Meta webhook delivery carries several messages
    (``entry`` x ``messaging``/``messages``: whatsapp_chat.py:112-119,
    messenger_chat.py:107-119, instagram_chat.py:116-126). An empty list means the delivery is
    legitimately ignored — a bot's own message, a non-message activity, an echo, a delivery
    receipt — and is not an error.

    ``response`` carries the platform-expected HTTP response when the platform SDK owns it:
    Bolt's ``AsyncSlackRequestHandler.handle`` (which also answers Slack's ``url_verification``
    handshake) and ``BotFrameworkAdapter.process_activity``'s ``invoke_response``. ``None``
    means the host returns the adapter's ``success_response``.
    """

    requests: List[InboundRequest] = field(default_factory=list)
    response: Any = None


class InboundAdapter(ABC):
    """Platform → Agent Kernel. Verifies, normalizes, and nothing else (design §1, §2)."""

    name: str                              # routing attribute value + outbound resolution key
    source: Source = Source.WEBHOOK
    webhook_path: str = ""                 # POST route the host mounts (WEBHOOK adapters)
    challenge_path: Optional[str] = None    # GET route, when the platform has a handshake

    async def verify(self, raw: Any) -> None:
        """Reject an unauthentic delivery. Concrete no-op by default (Decision Q4).

        Raises the platform's expected ``HTTPException`` (403 for the Meta HMAC checks and
        Telegram's secret token). Runs before ``parse`` and before any enqueue.
        """

    @abstractmethod
    async def parse(self, raw: Any) -> InboundParseResult:
        """Normalize one platform delivery. Never calls ChatService/AgentService/Runtime."""

    async def challenge(self, raw: Any) -> Any:
        """Answer the platform's subscription handshake (Meta's hub.challenge). Default 404."""
        raise HTTPException(status_code=404)

    def success_response(self) -> Any:
        """The platform-expected success body when the SDK did not produce one."""
        return {"status": "ok"}


class PollingInboundAdapter(InboundAdapter):
    """An inbound adapter whose events are pulled, not pushed (design §7). Gmail is the only one."""

    source = Source.POLLER
    poll_interval: float = 30.0            # adapters read their own config block for this

    @abstractmethod
    async def poll(self) -> List[Any]:
        """Return the raw events to parse this iteration. Must not run the agent."""

    def mark_handled(self, raw: Any) -> None:
        """Called after a raw event has been enqueued. Default no-op."""


class OutboundAdapter(ABC):
    """Agent Kernel → platform (design §1, §6)."""

    name: str
    MESSAGE_LIMIT: int = 4096              # per-platform chunk size for split_reply
    MAX_CHUNKS: Optional[int] = None       # None = unbounded
    ERROR_MESSAGE: str = "Sorry, there was an error processing your request."

    @abstractmethod
    async def deliver(self, reply: AgentReply, reply_context: Dict[str, str]) -> None:
        """Send the agent reply. Raising hands the message back to ConsumerLoop for retry."""

    @abstractmethod
    async def deliver_error(self, message: str, reply_context: Dict[str, str]) -> None:
        """Send a user-facing failure message so a user is never left silent."""

    async def acknowledge(self, reply_context: Dict[str, str]) -> Dict[str, str]:
        """Edge-side acknowledgement. Returns extra reply_context entries (default: none)."""
        return {}

    def split_reply(self, text: str) -> list:
        """Chunk a reply to the platform's message limit. One shared chunker (design §1)."""
```

Rules that govern the package:

1. **An adapter never executes.** No `InboundAdapter` or `OutboundAdapter` may import or call
   `ChatService`, `AgentService`, or `Runtime`. Everything an adapter produces is data; the only
   side effects it is allowed are platform API calls (download, acknowledge, deliver) and
   `AttachmentStore` writes.
2. **Adapters read only their own platform's config block.** Tokens, secrets, `agent`,
   `agent_acknowledgement` and `outbound_adapter` come from `AKConfig.get().<platform>`; nothing
   in the package reads `execution.*` except `IntegrationProducer` (which owns the transport) and
   `PollerRunner` (which owns the topology check).
3. **The inbound half is constructed by the application, the outbound half by the factory**
   (Decision Q1). Only outbound resolves by name, because the Response Handler holds a string.
4. **`verify` runs before `parse`, `parse` before any enqueue, and enqueue before the response.**
   Nothing may be enqueued for a delivery whose verification failed.
5. **`async` throughout.** Every platform SDK on both halves is async (`httpx`, `slack_bolt`,
   `botbuilder`), so `verify`/`parse`/`challenge`/`poll`/`deliver`/`deliver_error`/`acknowledge`
   are coroutines. The Response Handler bridges to them from its synchronous consumer thread
   (§7 below).

#### `factory.py` — `IntegrationAdapterFactory`

Follows the house pattern (`core/util/factory.py`), shaped like `QueueTransportFactory`
(`pipeline/transport/base.py:90-196`):

```python
class IntegrationAdapterFactory:
    _BUILTIN_NAMES = ("slack", "whatsapp", "messenger", "instagram", "telegram", "teams", "gmail")

    @classmethod
    def create_outbound(cls, name: str) -> OutboundAdapter: ...
```

Resolution, in order:

1. `name` is a built-in short name → read `AKConfig.get().<name>.outbound_adapter`. Non-empty →
   `resolve_dotted(value, base=OutboundAdapter)()`. Empty → the built-in, imported inside
   `require_extra(name, f"integration '{name}'")` so a missing SDK names its pip extra.
2. `name` contains a `.` → `resolve_dotted(name, base=OutboundAdapter)()`. This is the
   bring-your-own path for a platform that is not one of the seven: such an adapter pair sets
   `InboundAdapter.name` to the dotted path of its `OutboundAdapter`, since the `integration`
   attribute is the only thing that crosses the queue.
3. Otherwise → `AKConfigError(f"unknown integration adapter '{name}'; expected one of {...} or a
   dotted path to an OutboundAdapter subclass")`.

Instances are cached per resolved name on the factory (a `dict[str, OutboundAdapter]`), because
the Response Handler resolves on every output message and the Slack/Teams adapters own SDK
clients. The cache is keyed by name only; `AKConfig` is read once per name at construction, in
line with rule 4 of the pipeline package ("factories read config once and pass values in").

#### `producer.py` — `IntegrationProducer`

```python
class IntegrationProducer:
    REPLY_CONTEXT_BUDGET_BYTES = 8192

    def __init__(self, transport: Optional[QueueTransport] = None):
        self._producer = RequestProducer(transport)      # §3 below

    def enqueue(self, adapter_name: str, request: InboundRequest) -> Dict[str, Any]: ...
```

`enqueue` builds:

- **body**: `BaseRunRequest(prompt=..., agent=..., session_id=..., user_id=..., group_id=...,
  requests=request.requests)`, dumped with `model_dump(exclude_none=True)` — the same dump the
  REST path uses (`request_handler.py:66-71`).
- **attributes**: `{ATTR_REQUEST_ID: request.request_id, ATTR_INTEGRATION: adapter_name,
  **{f"{REPLY_CONTEXT_PREFIX}{k}": v for k, v in request.reply_context.items()}}`.
- **group_id**: `request.session_id`. **dedup_id**: `request.request_id` (design §3).
- `ATTR_USER_ID` is deliberately **not** stamped. That attribute is the WebSocket-entered marker
  (`agent_runner.py:156`, `response_handler.py:58`); an integration message is neither, and its
  user id travels in the body instead.

Budget enforcement (design §3, Decision Q3): before sending, sum the UTF-8 byte length of every
prefixed key and its value. Over `REPLY_CONTEXT_BUDGET_BYTES` raises
`ValueError(f"reply_context for integration '{adapter_name}' is {size} bytes, over the
{REPLY_CONTEXT_BUDGET_BYTES}-byte budget")` — before the transport client sees it, so the failure
names the adapter rather than surfacing as a broker error.

Measured contexts (§9 below lists the keys): Slack ~100 B, WhatsApp ~80 B, Messenger/Instagram
~40 B, Telegram ~30 B, Gmail a few hundred bytes (the subject dominates), Teams ~0.5–2 KB (the
serialized `ConversationReference`).

### 2. Queue contract — `pipeline/envelope.py`

New module-level constants beside the existing four (`envelope.py:8-11`):

```python
ATTR_INTEGRATION = "integration"      # presence marks a message as integration traffic
ATTR_THREAD = "thread"                # presence asks the runner to record the reply (design §14.1)
ATTR_AGUI = "agui"                    # presence marks a message as AG-UI traffic (design §15.1)
REPLY_CONTEXT_PREFIX = "reply_"       # every reply-to coordinate is stamped with this prefix
```

The three markers are orthogonal and never co-occur on one message: `integration` means "deliver
out-of-band through an outbound adapter, non-streamed"; `thread` means "record the reply";
`agui` means "stream, store the chunks, snapshot the state" (design Q14).

`QueueMessage` itself is unchanged. Reply context travels as flat string attributes because
`QueueMessage.attributes: Dict[str, str]` is already mapped to native metadata by every transport
(SQS `MessageAttributes` `transport/sqs.py:240-259`, Kafka headers `kafka.py:329`, NATS headers
`nats.py:257`), and because a body field would be fed to the agent: `BaseRunRequest` is
`extra="allow"` and `RequestBuilder._attach_additional_context` turns every unknown body field
into an `AgentRequestAny` (`core/chat_service.py:119-146`).

Teams' `ConversationReference` is an object, not a string, so it travels as one JSON-encoded
attribute value (`reply_conversation_reference`); every other platform's context is natively flat.

### 3. The reusable enqueue seam — `pipeline/producer.py`

New module holding the public seam design §4 requires:

```python
class RequestProducer:
    """Public input-queue producer: the enqueue seam shared by REST and integration edges."""

    def __init__(self, transport: Optional[QueueTransport] = None):
        self._transport = transport or QueueTransportFactory.create()

    def enqueue(
        self,
        body: BaseRunRequest,
        request_id: str,
        attributes: Optional[Dict[str, str]] = None,
        group_id: Optional[str] = None,
        dedup_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send one chat request to the input queue.

        :param request_id: Caller-supplied; stamped as ATTR_REQUEST_ID and used as the default
            dedup_id, so a platform retry dedupes against the platform's own id.
        """
```

Defaults reproduce `RestHandler._enqueue_request` (`request_handler.py:60-72`) bit for bit:
`json.dumps(body.model_dump(exclude_none=True))`, `{ATTR_REQUEST_ID: request_id}` merged with
`attributes`, `group_id or body.session_id`, `dedup_id or request_id`, returning
`transport.send(...) or {}`.

`RestHandler._enqueue_request` becomes a two-line delegation:

```python
def _enqueue_request(self, body: BaseRunRequest, request_id: str) -> Dict[str, Any]:
    return RequestProducer(self.get_transport()).enqueue(body, request_id)
```

It stays a method (not a call site rewrite) so `RestHandler.get_transport()` remains the
subclass injection point it is today, and both REST call sites (`:139`, `:286`) are untouched.

### 4. Prebuilt request lists on the wire — `core/model.py`, `core/chat_service.py`

The integrations' whole value is the `requests=` list they hand `ChatService.execute`
(`slack_chat.py:163`, `whatsapp_chat.py:293`, …): it carries downloaded attachments, Slack's
`AgentRequestAny(name="body", …)`, and — after §8 — attachment references. That list has to
survive the queue hop, and `BaseRunRequest` has no field for it: `files`/`images` are
`FileData`/`ImageData` and cannot express an `AgentRequestAttachmentRef` at all
(`core/model.py:73-89`).

- `core/model.py` gains a discriminated item alias and one typed field on `BaseRunRequest`:

  ```python
  AgentRequestUnion = Annotated[
      Union[AgentRequestText, AgentRequestFile, AgentRequestImage, AgentRequestAny, AgentRequestAttachmentRef],
      Field(discriminator="type"),
  ]

  class BaseRunRequest(BaseChatRequest):
      ...
      requests: Optional[List[AgentRequestUnion]] = None
  ```

  Typed, not an extra, for exactly the reason `scheduled_task_id`/`scheduled_time` are typed
  (`core/model.py:264-277`): an extra would reach the agent as `AgentRequestAny` context.
  `"requests"` is added to `RequestBuilder._attach_additional_context`'s `known_fields`
  (`core/chat_service.py:126-141`) as belt and braces for bodies written before the field existed.

- `ChatService.process_chat_request` and `process_stream_chat_sync` gain
  `requests: Optional[List[AgentRequest]] = None`, forwarded to `execute_sync` /
  `execute_stream_sync`, which already accept it. Existing callers are unaffected (the parameter
  defaults to `None`).

- `AgentRunner.process` and `StreamAgentRunner.process` pass `requests=body.requests`. This is not
  platform knowledge — a prebuilt request list is transport-neutral — so the runner stays
  platform-agnostic per design §5.

`ChatService._validate` already permits an absent prompt when a prebuilt list is supplied
(`core/chat_service.py:672-688`), which is what an image-only Slack or WhatsApp message needs.

### 5. Agent Runner changes — `pipeline/agent_runner.py`

- `_FORWARDED_ATTRIBUTES` (`:17`) gains `ATTR_INTEGRATION`; the membership filter at `:125`
  becomes a predicate so every `reply_`-prefixed attribute is forwarded too:

  ```python
  _FORWARDED_ATTRIBUTES = (ATTR_REQUEST_ID, ATTR_USER_ID, ATTR_ENDPOINT_URL, ATTR_INTEGRATION)

  def _forwarded(key: str) -> bool:
      return key in _FORWARDED_ATTRIBUTES or key.startswith(REPLY_CONTEXT_PREFIX)
  ```

  The existing three keep forwarding unchanged.
- The runner neither reads nor interprets `reply_context`; it copies it.
- **STREAM never applies to integration traffic** (design §5). `AgentRunner.run` selects
  `StreamAgentRunner` process-wide from `execution.mode` (`:87-88`), and `IOHandler` does the same
  at `io_handler.py:112`, so the per-message rule is implemented in `StreamAgentRunner` itself:

  ```python
  def process(self, message: QueueMessage) -> None:
      if message.attributes.get(ATTR_INTEGRATION):
          return super().process(message)     # no streaming consumer on a messaging platform
      ...
  ```

  `StreamAgentRunner.on_permanent_failure` delegates the same way, so an integration message's
  permanent failure produces the non-stream `{"error": ...}` body the Response Handler's
  integration branch expects rather than a `StreamChunk`.
- **AG-UI streams on the marker, whatever the mode** (design §15.2). The `integration` rule above
  routes *away* from streaming; AG-UI needs the opposite, and cannot rely on
  `execution.mode` because `IOHandler` only constructs `StreamAgentRunner` when the mode is
  `stream` (`io_handler.py:130`). The streaming body therefore moves out of
  `StreamAgentRunner.process` into `AgentRunner._process_stream`, and both classes route into it:

  ```python
  class AgentRunner:
      def process(self, message):
          if message.attributes.get(ATTR_AGUI):
              return self._process_stream(message)          # marker wins over the mode
          ...                                                # today's non-streamed path

      def _process_stream(self, message):                    # moved verbatim from StreamAgentRunner
          ...

  class StreamAgentRunner(AgentRunner):
      def process(self, message):
          if message.attributes.get(ATTR_INTEGRATION):
              return AgentRunner._process_nonstream(self, message)
          return self._process_stream(message)
  ```

  `_FORWARDED_ATTRIBUTES` gains `ATTR_AGUI` so the marker survives to the output message, which is
  what the Response Handler dispatches on.
- **The `ATTR_USER_ID` guard is scoped to WebSocket delivery.** `_process_stream` raises when a
  broker-transport message carries no `user_id` (`:218-219`) because those chunks are pushed to the
  user's sockets. An AG-UI message's chunks go to the response store, and AG-UI deliberately stamps
  no `ATTR_USER_ID` (the same rule `IntegrationProducer` follows, `producer.py:29-33`), so the guard
  becomes `if not message.attributes.get(ATTR_AGUI) and not message.attributes.get(ATTR_USER_ID)
  and transport != "in_memory"`.
- **The AG-UI state snapshot is produced here** (design §15.5, Q18), after the chunk loop, as one
  extra output chunk. The runner is the only process with a coherent before/after view of the
  session: `SessionStore.load` returns the process-local cached copy when it has one
  (`core/session/redis.py:39-43`), so an edge-side comparison would test the edge's own cached
  session against its own snapshot and never see a change.

  ```python
  def _send_agui_state(self, message, body, state_before) -> None:
      from ..integration.agui.state import AGUIState          # lazy: §14.9's rule
      ...
      if state_after != state_before:
          self._send_to_output(message, {"agui_state": state_after}, None, dedup_suffix=f"{n}-state")
  ```

  `state_before` is taken immediately before the run, in this process, by the same lazy helper.
  When the two match, nothing is sent and the edge emits no `StateSnapshotEvent`.

### 6. Response Handler dispatch — `pipeline/response_handler.py`

`process` gains one branch **before** the `execution.mode` branch (`:51-66`); a message without
`ATTR_INTEGRATION` takes today's path unchanged:

```python
def process(self, message: QueueMessage) -> None:
    integration = message.attributes.get(ATTR_INTEGRATION)
    if integration:
        self._deliver_integration(message, integration)
        return
    if message.attributes.get(ATTR_AGUI):
        self._store_chunk(message)          # design §15.3 — before the mode branch
        return
    mode = AKConfig.get().execution.mode
    ...
```

The AG-UI branch sits alongside the integration one and **before** the `execution.mode` branch for
the same reason design §15.2 gives on the runner side: an app serving AG-UI need not be configured
`mode: stream`, so the global mode must not decide where an AG-UI chunk goes. It reuses
`_store_chunk` unchanged, including its `supports_chunk_streaming()` guard — but that guard is now
a backstop rather than the first line of defence, because §10 fails fast at handler construction.

`_deliver_integration`:

1. `adapter = IntegrationAdapterFactory.create_outbound(integration)`.
2. `reply_context = {k.removeprefix(REPLY_CONTEXT_PREFIX): v for k, v in message.attributes.items()
   if k.startswith(REPLY_CONTEXT_PREFIX)}`.
3. `body = json.loads(message.body)`; `status = int(message.attributes.get(ATTR_STATUS_CODE, "200"))`.
4. `status >= 400` → log `body.get("error")` at error level and
   `await adapter.deliver_error(adapter.ERROR_MESSAGE, reply_context)`. Raw exception text is
   never sent to a platform user; the constant is a class attribute so an adapter can reword it.
5. Otherwise → `await adapter.deliver(AgentReplyText(response=body.get("result", "")),
   reply_context)`.

**The reply arrives as text, always.** `AgentRunner` serializes the reply through
`ResponseBuilder.build_response`, which writes `{"result": str(result), "session_id": ...}`
(`core/chat_service.py:314-320`), so no typed reply survives the output queue. That is not a
regression: every integration already collapses the reply the same way today
(`slack_chat.py:172`, `teams_chat.py:530`). `deliver` keeps the `AgentReply` parameter type from
design §1, and its docstring states that on the queue path it is always an `AgentReplyText`;
richer replies would need an output-queue wire-format change, which is out of scope.

`on_permanent_failure` (`:68-108`) gains the same leading branch, calling
`deliver_error(adapter.ERROR_MESSAGE, reply_context)` inside the method's existing
`try`/`except Exception` so a delivery failure there cannot take down the consumer thread —
matching the "clients never hang" guarantee the rest of the method implements.

Delivery failures in `process` propagate, so `ConsumerLoop` retries up to
`execution.queues.output.max_receive_count` and then hands over to `on_permanent_failure` — the
same contract `_broadcast` documents (`:159-166`).

**Sync/async bridge.** `ConsumerLoop` drives an async `process` via `asyncio.run`
(`consumer.py:137-141`), but `on_permanent_failure` is always called synchronously
(`consumer.py:132`), so `ResponseHandler` cannot simply become async. `AgentHandler._run_async_sync`
(`core/chat_service.py:224-242`) is the house pattern for this and is promoted to
`core/util/async_bridge.py::run_async_sync`, with `AgentHandler._run_async_sync` delegating to it
so its callers and behaviour are unchanged. `IntegrationAdapterFactory` is imported **lazily,
inside** `ResponseHandler._outbound_adapter`: `pipeline` imports `core` and `api` only, and a
module-scope import would make every pipeline process (a Lambda included) pay for the platform
SDKs. This is the shape `core/tool.py` already uses to reach the AG-UI state helpers. Both Response Handler branches call
`run_async_sync(adapter.deliver(...))`.

### 7. Hosting

#### `WebhookRESTRequestHandler` (design §7, Decision Q7)

```python
class WebhookRESTRequestHandler(RESTRequestHandler):
    """Generic host for a WEBHOOK InboundAdapter: mounts its routes, verifies, parses, enqueues."""

    requires_pipeline = True

    def __init__(self, adapter: InboundAdapter, producer: Optional[IntegrationProducer] = None): ...
```

`get_router()` mounts `POST adapter.webhook_path` → `self._handle`, and `GET
adapter.challenge_path` → `adapter.challenge` when the adapter declares one. It mounts **no**
`/health` route: `RESTAPI._create_app` registers `/health` before including any router
(`api/http.py:59-61`), so the per-handler copies the seven classes carry today are already
shadowed and their removal changes nothing.

`_handle(request)`:

```
await adapter.verify(request)                       # HTTPException propagates as the platform's status
result = await adapter.parse(request)               # InboundParseResult
outbound = IntegrationAdapterFactory.create_outbound(adapter.name)   # only if result.requests
for inbound in result.requests:
    inbound.reply_context |= await outbound.acknowledge(inbound.reply_context)
    await asyncio.to_thread(producer.enqueue, adapter.name, inbound)
return result.response if result.response is not None else adapter.success_response()
```

- `verify` raising `HTTPException` gives the platform its expected status (403 for the Meta HMAC
  checks and Telegram's secret token; Slack and Teams reject inside their SDK dispatch during
  `parse`, Teams as 401 per `teams_chat.py:120-122`).
- An empty `result.requests` returns the success response and enqueues nothing.
- The enqueue is offloaded with `asyncio.to_thread` because `QueueTransport.send` is synchronous,
  exactly as `RestHandler.enqueue_and_wait` does (`request_handler.py:139`).
- An enqueue failure propagates as a 500, so the platform retries (design §11). This is a change
  for the three Meta platforms, which swallow everything today — see Behavioural changes.
- The route returns as soon as the last message is enqueued; it never awaits the agent run.
  Target: webhook handler p99 under 1 s excluding attachment download.

#### The pipeline fail-fast (design §7, Decisions Q2 and Q9)

- `RESTRequestHandler` gains `requires_pipeline: bool = False` (`api/handler.py:16`).
- `RESTAPI.run` raises after the existing delegation branch and **outside** its `cls is RESTAPI`
  guard, so subclasses (`AWSRestAPI`, `AWSWebsocketAPI`) are covered too:

  ```python
  # `is True`, not truthiness: the flag is a declared bool, and a bare test double (or any
  # auto-attribute proxy) answers every getattr with a truthy object.
  offenders = sorted({type(h).__name__ for h in handlers or [] if getattr(h, "requires_pipeline", False) is True})
  if offenders:
      raise AKConfigError(
          f"{', '.join(offenders)} require the queue pipeline: start them with "
          "IOHandler.run(handlers=[...]) instead of RESTAPI.run([...])"
      )
  ```

  Placed after the branch at `api/http.py:99-106`, so the no-handlers delegation path is
  untouched and the three delegation conditions are unchanged. `IOHandler` needs no change: it
  calls `RESTAPI.build_app` (`io_handler.py:91`), not `run`.

  Without this, the failure is silent and worse than a crash:
  `QueueTransportFactory.resolve_type()` returns `in_memory` when no queues block is declared
  (`transport/base.py:111-114`), so the webhook would enqueue successfully into a queue that no
  runner drains — the platform gets its 200 and the user never gets a reply.

#### `PollerRunner` (design §7, Decisions Q5 and Q7)

Lives in `integration/adapter/poller.py`, not `pipeline/`: it hosts an `InboundAdapter`, and
`pipeline` may import only `core` and `api` (architecture rule 2). It mirrors `AgentRunner`'s
entry-point shape exactly:

```python
class PollerRunner:
    def __init__(self, adapter: PollingInboundAdapter, producer: Optional[IntegrationProducer] = None): ...

    def start(self, exit_on_shutdown: bool = True) -> None: ...

    @classmethod
    def run(cls, adapter: PollingInboundAdapter) -> None:
        if QueueTransportFactory.resolve_type() == "in_memory":
            raise AKConfigError(
                "the in_memory transport runs in-process: start IOHandler(pollers=[...]) "
                "(single-process topology) instead of PollerRunner"
            )
        ThreadRunner.install_shutdown_signal_handlers(cls._log)
        cls(adapter).start()
```

`start` runs one `ThreadRunner.Task` (`stop_all_on_failure=True, graceful=True`) whose loop is:

```
while not ThreadRunner.shutdown_event.is_set():
    for raw in await adapter.poll():
        result = await adapter.parse(raw)
        for inbound in result.requests:
            producer.enqueue(adapter.name, inbound)
        adapter.mark_handled(raw)
    ThreadRunner.shutdown_event.wait(adapter.poll_interval)
```

Errors inside one iteration are logged and the loop continues (today's behaviour,
`gmail_chat.py:135-141`). `shutdown_event.wait(...)` rather than `time.sleep` is what lets a
30-second poll interval drain promptly, satisfying design §7's "observe `shutdown_event` once per
iteration"; `graceful=True` then marks the drain a clean exit.

A poller produces into the input queue only; it never delivers replies.

Deployment: its own workload at one replica. Chart support is out of scope for this CR (design
Non-goals) — `PollerRunner.run(adapter)` is the documented container entry point and an operator
wires the workload. Duplicate polling is not a correctness failure (`dedup_id` is the platform
message id and every transport deduplicates on it), so a second replica wastes API quota rather
than double-running the agent — but see the Gmail note in §9.

#### `IOHandler` co-hosting (design §7)

`IOHandler.run` gains a third parameter:

```python
def run(cls, auth_validator=None, handlers=None, pollers: Optional[list["PollerRunner"]] = None) -> None:
```

typed under `TYPE_CHECKING` (the same trick pipeline already uses for `deployment` types), so no
runtime import of `integration` is introduced. Behaviour:

- `in_memory` → one extra `ThreadRunner.Task` per poller, appended in the existing `single_process`
  branch (`io_handler.py:111-117`) with `execution_function=lambda p=p: p.start(exit_on_shutdown=False)`,
  `thread_name=f"poller-{adapter.name}"`, `stop_all_on_failure=True`.
- broker transport → the pollers are **not** started, and a warning is logged naming
  `PollerRunner.run(adapter)` as the container to start — the same shape as the existing
  `auth_validator ignored` warning (`io_handler.py:79-84`). Poller lifetime must not be coupled to
  webhook replica count: scaling the webhook tier for Slack load would otherwise multiply Gmail
  pollers.

No `IOHandler` change is needed for webhook adapters: `run(handlers=[...])` already mounts app
handlers alongside the pipeline's own `RequestHandler()` (`io_handler.py:73`).

### 8. Attachment offload — `core/multimodal/storage/offload.py`

Attachments are stored in the `AttachmentStore` at the inbound edge and travel as
`AgentRequestAttachmentRef` (`core/model.py:73-89`), never as inline base64.
`ConversationThreadManager.store_attachments` (`integration/thread/manager.py:144-205`) already
performs exactly this rewrite, so its core is extracted rather than reimplemented. It cannot be
called directly — it returns `ThreadAttachment` references and lives in `integration/thread/`,
which the adapter package must not depend on — so the shared piece moves to `core/`:

```python
@dataclass
class StoredAttachment:
    attachment_id: str
    name: str
    mime_type: str


def offload_attachments(
    session_id: str,
    requests: List[AgentRequest],
    *,
    attachments_disabled_error: str,
    session_cache_error: str,
) -> tuple[List[AgentRequest], List[StoredAttachment]]:
    """Replace every image/file request with an AgentRequestAttachmentRef, in place."""
```

The two guards are carried over unchanged in behaviour (`manager.py:165-181`): attachment-bearing
requests require `multimodal.enabled: true`, and `multimodal.storage_type: session_cache` is
rejected because it writes into a session copy the runner process never sees. The messages are
caller-supplied so `ConversationThreadManager` keeps its current wording verbatim while the
adapter package supplies integration-specific wording:

- disabled: `"Attachments from messaging integrations require multimodal support — set
  multimodal.enabled: true in config.yaml to accept images and files"`
- session_cache: `"multimodal.storage_type 'session_cache' is not supported for messaging
  integrations — the agent runs in a different process; use in_memory, redis, or dynamodb"`

`ConversationThreadManager.store_attachments` keeps its signature and return type, mapping
`StoredAttachment` → `ThreadAttachment`. Attachments stay exempt from `max_attachments` eviction
(`max_attachments=sys.maxsize`) on both callers.

Download stays at the edge (it needs the platform token) and stays bounded by
`api.max_file_size`.

### 9. The seven adapters

Each `integration/<platform>/adapter.py` holds the platform's pair; `<platform>_chat.py` is
deleted; `integration/<platform>/__init__.py` exports the pair instead of the handler, so the
public aliases (`agentkernel.slack`, …) keep working with new contents (design §10).

| Platform | `name` | `session_id` (unchanged) | `request_id` | `reply_context` keys | `MESSAGE_LIMIT` |
|---|---|---|---|---|---|
| Slack | `slack` | `thread_ts or ts` (`slack_chat.py:81`) | `f"slack:{channel}:{ts}"` | `channel`, `thread_ts`, `user`, `ack_ts`, `ack_channel` | 3000, 5 chunks |
| WhatsApp | `whatsapp` | `from` (`whatsapp_chat.py:278`) | `message.id` | `to`, `reply_to_message_id` | 4096 |
| Messenger | `messenger` | `sender.id` (`messenger_chat.py:193`) | `message.mid` | `recipient_id` | 2000 |
| Instagram | `instagram` | `sender.id` (`instagram_chat.py:211`) | `message.mid` | `recipient_id` | 1000 |
| Telegram | `telegram` | `str(chat.id)` (`telegram_chat.py:183`) | `str(update_id)` | `chat_id` | 4096 |
| Teams | `teams` | `conversation.id` (`teams_chat.py:254`) | `activity.id` | `conversation_reference` (JSON) | 8000 |
| Gmail | `gmail` | `threadId or sender` (`gmail_chat.py:267`) | Gmail `message.id` | `to`, `subject`, `thread_id`, `message_id`, `in_reply_to` | — |

Per-platform behaviour each adapter must preserve (design §10):

- **Slack.** `verify` inherits the no-op; `parse` runs Bolt's `AsyncSlackRequestHandler.handle`
  and captures the event from the registered `@app.event("message")` callback, returning Bolt's
  `Response` as `InboundParseResult.response` (this is what answers the `url_verification`
  handshake). Bot's-own-message skip, `<@bot>` mention stripping, audio/video rejection,
  oversized-file rejection, download-failure message, and the `AgentRequestAny(name="body", …)`
  context entry all move into `parse`. `acknowledge` posts the "…:rolling-loader:" message and
  returns `{"ack_ts": ts, "ack_channel": channel}`; `deliver` performs the `chat_update` that
  strips the loading emoji and then posts the blocks. `split_reply` is overridden to build
  Slack blocks (`slack_chat.py:201-230` verbatim, including the 5-chunk truncation notice).
  Slack has no usable id at the handler — Bolt hands over the inner event, not the envelope
  (`slack_chat.py:47-50`) — hence the synthesized `request_id`, which is unique per message.
- **WhatsApp / Messenger / Instagram.** `verify` performs the `X-Hub-Signature-256` HMAC check
  (`whatsapp_chat.py:131-145`, `messenger_chat.py:125-139`, `instagram_chat.py:133-147`) and
  raises `HTTPException(403)`; `challenge` answers `hub.challenge`
  (`whatsapp_chat.py:73-91` and siblings). `parse` iterates every entry/message and returns one
  `InboundRequest` per message. Instagram keeps its echo skip (`instagram_chat.py:166-168`);
  Messenger and Instagram keep postback handling; WhatsApp keeps its interactive-reply text
  extraction and its audio/video rejection message. Messenger's and Instagram's `mark_seen` +
  `typing_on` become `acknowledge`; `typing_off` moves to the start of `deliver`.
- **Telegram.** `verify` checks `X-Telegram-Bot-Api-Secret-Token` (`telegram_chat.py:57-61`).
  `parse` receives the **whole update object**, not `body["message"]` (`telegram_chat.py:79`), so
  `update_id` is available as `request_id`; it dispatches `message` / `edited_message` /
  `callback_query` and keeps `/start` and `/help` as adapter-local replies that return no
  `InboundRequest`. `acknowledge` sends the typing action. The `BackgroundTasks` deferral
  (`telegram_chat.py:52,65`) is removed as redundant.
- **Teams.** `verify` inherits the no-op; `parse` runs
  `BotFrameworkAdapter.process_activity` and captures the activity in the turn callback,
  returning the `invoke_response` as `InboundParseResult.response` and mapping `PermissionError`
  to 401 (`teams_chat.py:118-129`). Mention stripping, tenant resolution, group resolution, the
  four attachment outcome lists (rejected / oversized / failed / unauthorised) and the MSAL /
  Bot-Framework token acquisition all move into `parse`. `TurnContext.get_conversation_reference`
  (`teams_chat.py:173`) is serialized into `reply_conversation_reference`; `deliver` deserializes
  it and sends through `continue_conversation` (`teams_chat.py:191-197`), which is exactly today's
  proactive delivery, now running in the Response Handler process. `acknowledge` sends the
  `agent_acknowledgement` line.
- **Gmail** is the only `PollingInboundAdapter`. `poll()` runs today's unread-label query with the
  sender/subject filters (`gmail_chat.py:148-230`) and returns the message ids that pass;
  `parse(message_id)` fetches the message, builds the `From:/Subject:/body` prompt with thread
  history (`gmail_chat.py:288-322`), extracts attachments, and offloads them. `deliver` sends the
  threaded reply with the `In-Reply-To`/`References` headers and the configured signature
  (`gmail_chat.py:448-503`) and then marks the message read (`gmail_chat.py:612-625`) — the same
  order as today. `authenticate()` stays on the adapter and is called by `poll()` on first use.
  The in-process `_processed_emails` set is **retained** on the adapter: an email stays unread
  until the reply is delivered, so without it the poller would re-enqueue it every interval, and
  the transport dedup window (5 minutes on SQS FIFO) is shorter than a slow agent turn. This is
  why the poller runs at one replica.

### 10. AG-UI on the pipeline — `integration/agui/pipeline.py`, the redis/valkey stores

Implements design §15. Three pieces: the chunk-streaming capability on the shared stores, the edge
half extracted out of `AGUIRequestHandler`, and the queue-mode sibling that enqueues and drains.

#### 10.1 `blpop` on the shared driver — `core/util/driver/redis_like.py`

One method, in the driver's existing list section beside `rpush`/`lpop`/`llen`/`lrange`:

```python
def blpop(self, key: str, timeout: float) -> Optional[str]:
    """BLPOP one element, blocking up to `timeout` seconds. None on timeout."""
```

- Both backends inherit it: the `valkey` client is a `redis-py` fork with an identical API, which
  is why `_RedisLikeDriver` exists (`redis_like.py:16-19`).
- `redis-py` returns `(key, value)` or `None`; the driver returns the value alone, decoded, so
  stores never touch the tuple shape. `timeout=0` means "block forever" in the Redis protocol, so
  the driver floors a non-positive timeout to `1` rather than hanging a worker thread indefinitely.
- The driver reads no config and knows nothing about chunks — it is `core/util/`, consumed by both
  `pipeline/` and `deployment/` (architecture coupling rule).

#### 10.2 The chunk-streaming capability — `pipeline/response_store/redis.py`, `valkey.py`

Both stores implement the base's optional trio (`response_store/base.py:54-72`) and return `True`
from `supports_chunk_streaming()`. The two implementations are identical apart from their driver,
exactly as their existing four methods are, so the bodies live in one mixin,
`_ChunkStreamMixin`, in a new `pipeline/response_store/chunk_stream.py`:

```python
class _ChunkStreamMixin:
    """add_chunk/stream/close_stream over a Redis-like list, for a single blocking reader."""

    _CLOSE_SENTINEL = {"__ak_closed__": True}

    def _chunk_key(self, request_id: str) -> str: ...           # f"{prefix}{request_id}:chunks"

    def supports_chunk_streaming(self) -> bool:
        return True

    def add_chunk(self, request_id, chunk) -> None:
        key = self._chunk_key(request_id)
        self._driver.rpush(key, json.dumps(chunk))
        self._driver.expire(key)                                 # the store's configured TTL

    def stream(self, request_id, chunk_timeout=None) -> Iterator[Dict]:
        # same contract as InMemoryResponseStore.stream (in_memory.py:63-90)
        ...

    def close_stream(self, request_id) -> None:
        self._driver.rpush(self._chunk_key(request_id), json.dumps(self._CLOSE_SENTINEL))
        self._driver.expire(self._chunk_key(request_id))
```

Rules the implementation holds to, each mirroring `InMemoryResponseStore` so the two behave
identically under the same contract test:

1. **A list plus a blocking pop, not a Redis Stream** (design Q17). Single consumer, at-most-once,
   drop-on-close — consumer groups would add machinery with nothing to show for it.
2. **`stream` stops on the chunk carrying `done`, or on the sentinel**, and deletes the key in a
   `finally` — the same shape as `in_memory.py:86-90`, so a completed or abandoned run leaves no
   key behind even before the TTL.
3. **A timeout raises `TimeoutError`** with the same message text the in-memory store uses
   (`in_memory.py:83`), because `RequestHandler._sse_stream` already catches `TimeoutError` and
   turns it into an error frame (`request_handler.py:297-300`).
4. **The default `chunk_timeout` is the response store's own budget**, `retry_count * delay`, read
   the same way `in_memory.py:70-75` reads it — the store owns its config section, the driver does
   not.
5. **`close_stream` pushes a sentinel rather than deleting the key.** A parked `BLPOP` is not
   released by a `DEL`; the sentinel is what unblocks the reader, and the reader's `finally` then
   deletes the key. Same reasoning as the in-memory store's `queue.Queue` sentinel
   (`in_memory.py:93-102`).
6. **`delete_message` also drops the chunk key**, matching `in_memory.py:51-55`.

`dynamodb` is left untouched and keeps returning `False` from the base: it has no blocking read, and
per-chunk polling is what design §15 exists to avoid.

#### 10.3 The extracted edge half — `integration/agui/handler.py`

`AGUIRequestHandler._run` currently does validation, session setup and the stream hand-off in one
method (`handler.py:180-211`). Everything up to (but excluding) the `StreamingResponse` is
extracted, unchanged, into one protected method both handlers call:

```python
class AGUIEdge(NamedTuple):
    agent: Agent
    handler: AgentHandler
    session: Session
    run_input: Any            # RunAgentInput
    requests: list
    encoder: Any
    user_id: Optional[str]

def _prepare(self, agent_name: str, request: Request) -> AGUIEdge:
    """Authorise, resolve, parse, map, prepare the handler, land the client fields on the
    session, and build the encoder. Every failure here is still an HTTP status."""
```

- The 404/400/422 contract, `_warn_if_unreadable`, and `set_agui_session_keys` all move inside it
  verbatim, so the two handlers cannot drift.
- `state_before = AGUIState.snapshot_state(session)` stays in the **direct** handler's `_run`, not
  in `_prepare`: on the queue path the runner takes its own snapshot (design §15.5), so the edge
  taking one there would be dead code implying a comparison that never happens.
- `_run` and `_events` are otherwise unchanged, and the direct handler's behaviour is identical
  before and after.

#### 10.4 The queue-mode sibling — `integration/agui/pipeline.py`

```python
class AGUIPipelineRequestHandler(AGUIRequestHandler):
    """Queue-mode AG-UI: enqueue the run, keep the socket, stream the reply back out of the
    response store. The queue-mode counterpart of AGUIRequestHandler, as
    ThreadRequestHandler is of AgentThreadRequestHandler.

        IOHandler.run(handlers=[AGUIPipelineRequestHandler(auth_validator=...)])
    """

    requires_pipeline = True
```

- **Construction fails fast** (design §15.7): after `super().__init__`, it resolves the transport
  and the response store and raises `AKConfigError` when
  `store.supports_chunk_streaming()` is `False`, naming the store type and the supported ones. This
  is before the first request, matching Q2's posture; `ResponseHandler._store_chunk`'s own guard
  stays as the backstop.
- **`get_router` is inherited unchanged.** AG-UI owns `agui.prefix`, so it collides with no
  pipeline route and mounts through `handlers=[...]`; `IOHandler` needs no change (design §15.8,
  contrast §14.5).
- `_run` is overridden; `_events` is replaced by `_events_from_store`:

  ```python
  async def _run(self, agent_name, request) -> StreamingResponse:
      edge = self._prepare(agent_name, request)                  # §10.3, shared
      Runtime.current().sessions().store(edge.session)            # design §15.6
      request_id = str(uuid.uuid4())
      body = BaseRunRequest(
          prompt="", agent=edge.agent.name, session_id=edge.run_input.thread_id,
          user_id=edge.user_id, requests=edge.requests,
      )
      await asyncio.to_thread(
          RequestProducer(self._transport).enqueue, body, request_id,
          {ATTR_AGUI: "1"}, edge.run_input.thread_id, request_id,
      )
      return StreamingResponse(
          self._events_from_store(edge, request_id), media_type=edge.encoder.get_content_type()
      )
  ```

  - `prompt=""` is deliberate and legal: `ChatService._validate` requires a prompt only when
    `requests` is `None` (`core/chat_service.py:680-686`), and AG-UI always supplies a prebuilt
    list. It is not `None` because `BaseRunRequest.prompt` is a required `str`.
  - `group_id = thread_id` gives per-conversation FIFO ordering, and `dedup_id = request_id`
    matches the REST path. The `request_id` is a fresh `uuid4`, not a client value: `runId` is
    caller-supplied and a client that reused one would collide in the response store.
  - `asyncio.to_thread` because `RequestProducer.enqueue` is synchronous, exactly as
    `RequestHandler._run_chat_stream` does it (`request_handler.py:288`).
- `_events_from_store` keeps the protocol bracket and reuses the same mapper and encoder as the
  direct path:

  ```python
  async def _events_from_store(self, edge, request_id) -> AsyncGenerator[str, None]:
      yield edge.encoder.encode(RunStartedEvent(...))              # before any store read
      store, iterator = self._store, self._store.stream(request_id)
      try:
          while True:
              record = await asyncio.to_thread(next, iterator, None)
              if record is None:
                  break
              if record.get("error"):
                  yield edge.encoder.encode(RunErrorEvent(message=record["error"])); return
              if "agui_state" in record:
                  yield edge.encoder.encode(StateSnapshotEvent(snapshot=record["agui_state"]))
                  continue
              chunk = StreamChunk.model_validate(record)
              if chunk.event is not None:
                  agui_event = AGUIMapper.to_agui(chunk.event)
                  if agui_event is not None:
                      yield edge.encoder.encode(agui_event)
      except TimeoutError as e:
          yield edge.encoder.encode(RunErrorEvent(message=str(e))); return
      except Exception as e:
          self._log.exception(...); yield edge.encoder.encode(RunErrorEvent(message=str(e))); return
      finally:
          store.close_stream(request_id)
      yield edge.encoder.encode(RunFinishedEvent(...))
  ```

  - `asyncio.to_thread(next, iterator, None)` for the same reason `RequestHandler._sse_stream` does
    it (`request_handler.py:294`): `stream()` is a **synchronous** blocking iterator, and awaiting it
    on the event loop would freeze every other request on the replica.
  - `close_stream` in a `finally` releases the per-request state even when the client disconnects
    mid-stream — the case `request_handler.py:308-316` documents.
  - `StreamChunk.model_validate` reconstructs the typed event because `StreamEvent` is a
    `Field(discriminator="type")` union whose members carry only `str`/`int`/`bool`
    (`core/event.py:1-27`, `:131-146`), so `chunk.event` round-trips through the queue and
    `AGUIMapper.to_agui`'s `match event.type` still resolves.
  - A chunk with neither `event` nor `agui_state` (a bare `delta`, or the terminal `done`) yields
    nothing — AG-UI's content comes from the typed events, and `done` is represented by
    `RunFinished`.
  - **Exactly one terminal event** on every path: `RunFinished` on a clean drain, `RunError` on an
    error chunk (including the one `on_permanent_failure` writes), on a store timeout, and on any
    unexpected exception.
- `agentkernel/integration/agui/__init__.py` exports it beside `AGUIRequestHandler`, so
  `from agentkernel.agui import AGUIPipelineRequestHandler` works through the existing
  `agui.py` star-import alias.

### Consumer changes

| Consumer | Change |
|---|---|
| `examples/api/{slack,whatsapp,messenger,instagram,telegram,teams}/server.py` | `RESTAPI.run([Agent<X>RequestHandler()])` → `IOHandler.run(handlers=[WebhookRESTRequestHandler(<X>InboundAdapter())])` |
| `examples/api/gmail/server.py` | The `asyncio.run(handler.start_polling())` main is replaced by `IOHandler.run(pollers=[PollerRunner(GmailInboundAdapter())])` (single-process) |
| `examples/api/messenger/example_custom_handler.py`, `examples/api/whatsapp/example_custom_handler.py` | Subclass the inbound adapter instead of the handler; the overridden hook is `parse`, not `_handle_message` |
| `e2e/app/app.py` | Same migration: `_handlers()` returns `WebhookRESTRequestHandler(...)` instances, `_maybe_start_gmail` returns a `PollerRunner`, and `main()` calls `IOHandler.run(handlers=..., pollers=...)`. The optional-credential degradation (`_append_optional`, `app.py:59-74`) is kept — adapters still raise at construction on incomplete config. **Not named in `design.md` §7, which lists only the examples and docs; it is the one non-example in-repo consumer of the seven handler classes.** |
| `examples/api/*/config.yaml` | Each gains an `execution.queues` block (or relies on the `in_memory` default) — verified per example when the plan's example iteration runs |

The `ak-deployment/ak-k8s` chart is **not** touched (design Non-goals): the webhook adapters ride
the existing io tier and its CPU HPA (`templates/hpa-io.yaml`), and the poller tier's Deployment is
a follow-up CR.

| `examples/api/agui/server.py` | **Unchanged.** It mounts `AGUIRequestHandler` on `RESTAPI.run`, which stays the documented default (design §15.10). A second example is not added in this CR; the queue-mode handler is documented in `docs/docs/integrations/agui.md` |

Unchanged and verified: every non-integration `RESTRequestHandler`
(`AgentRESTRequestHandler`, `AgentThreadRequestHandler`, `ScheduleRESTRequestHandler`,
`AGUIRequestHandler`) inherits `requires_pipeline = False` and is unaffected; `RequestHandler` and
its `ThreadRequestHandler` subclass declare it (design §14.6), and `AGUIPipelineRequestHandler`
declares it (design §15.8); `ECSIOHandler` and the `deployment/aws` runners are untouched
(design §13) — including `deployment/aws/core/response_store/{redis,valkey}.py`, which are separate
classes from the pipeline stores §10.2 changes and keep their mailbox-only surface.

### Config changes

Each of the seven platform blocks (`core/config.py:158-221`) gains exactly one field:

```python
outbound_adapter: str = Field(
    default="",
    description="Dotted path to an OutboundAdapter subclass replacing the built-in <platform> outbound adapter",
)
```

- No new top-level section; existing YAML and `AK_*` env vars keep working unchanged.
- Existing fields (`agent`, `agent_acknowledgement`, tokens, secrets, `api_version`,
  `poll_interval`, `label_filter`, `token_file`) are unchanged in name, type, default, and
  description.
- There is deliberately no inbound override: the application constructs the inbound adapter
  itself (Decision Q1), so bring-your-own inbound is just passing a different instance.
- Data compatibility: nothing written before this change is read back differently. Response-store
  records, session data, thread records, and attachment-store entries keep their exact layouts.
- §10 adds **no** config fields. AG-UI queue mode is selected by mounting
  `AGUIPipelineRequestHandler` instead of `AGUIRequestHandler` — mounting is what enables the
  surface, exactly as `_AGUIConfig`'s own docstring says of the direct handler
  (`core/config.py:841-843`). The `agui` block keeps every field, name, type and default.
- §10.2 adds a new key shape to the redis/valkey response-store keyspace:
  `{prefix}{request_id}:chunks`, a list, alongside the existing `{prefix}{request_id}` string. It
  carries the store's configured TTL and is deleted when a stream ends, so it neither collides with
  nor outlives the records already there.

### Behavioural changes

All intentional; each is user-visible or operator-visible.

1. **The agent runs outside the webhook turn on all seven platforms.** A slow LLM call can no
   longer become a platform-level delivery timeout and a redelivered event. This is the change.
2. **Meta webhooks no longer swallow errors.** WhatsApp, Messenger and Instagram return
   `{"status": "ok"}` from inside a bare `except` today (`whatsapp_chat.py:126-129`,
   `messenger_chat.py:120-123`, `instagram_chat.py:128-131`). After this change a parse or
   enqueue failure returns 500 and the platform retries. Justification: design §11 requires an
   enqueue failure to be retried; a dropped message today is invisible. Verification failures keep
   returning 403.
3. **Attachment-bearing messages now require `multimodal.enabled: true`** and reject
   `multimodal.storage_type: session_cache` on all seven platforms (design §8). Today an
   attachment reaches the agent as inline base64 with multimodal disabled. This breaks an existing
   app that receives attachments with multimodal off; the rejection message names the setting.
4. **A platform retry no longer double-runs the agent** within the transport's dedup window,
   because `dedup_id` is the platform's own message id. Slack, which has no usable id at the
   handler, synthesizes `slack:{channel}:{ts}`.
5. **Agent-failure wording is unified.** A failed run (status ≥ 400 on the output message,
   including "no agent available") now delivers `OutboundAdapter.ERROR_MESSAGE`
   ("Sorry, there was an error processing your request.") instead of each platform's own sentence
   (e.g. `slack_chat.py:166`, `whatsapp_chat.py:296`). Deliberate: the raw error string must not
   reach a platform user, and it is logged at error level instead. Adapters may override the
   constant.
6. **Telegram no longer defers to `BackgroundTasks`** and parses the whole update object rather
   than `body["message"]`, so `update_id` is available.
7. **Teams' proactive `continue_conversation` runs in the Response Handler process**, not the
   webhook process. The acknowledgement is still sent inline at the edge.
8. **Both processes hold platform send credentials** (design §11, Decision Q6): the edge needs the
   send token for attachment download and the acknowledgement; the Response Handler needs it for
   `deliver`. Deployment note, not a code change.
9. **Integration apps must change their mounting call** — `RESTAPI.run([...])` now raises
   `AKConfigError`. Combined with the deletion of the seven handler classes (Decision Q8), this is
   the CR's breaking change; both edits land in the same file of a user's app.
10. **A REST body field named `requests` is now typed** rather than surfaced to the agent as
    `AgentRequestAny` context. A caller who was relying on that (undocumented) behaviour now gets a
    validation error unless the value matches `List[AgentRequestUnion]`.

**Non-changes** (verified against the base branch):

- `QueueMessage`'s shape (`envelope.py:21-37`) — only two new module-level constants.
- Every transport; no new queue; no change to any `QueueTransport`/`TransportConsumer` method.
- REST and WebSocket delivery for messages without `ATTR_INTEGRATION` — `ResponseHandler.process`
  reaches the identical mode branch.
- `RESTAPI.run`'s delegation rule keeps its three conditions (`cls is RESTAPI`, no handlers,
  `in_memory`); the new check sits after it and every existing handler defaults to
  `requires_pipeline = False`.
- `RestHandler._enqueue_request`'s envelope: same body dump, same attributes, same `group_id`,
  same `dedup_id`.
- Per-platform `session_id` derivation, message chunk limits, acknowledgement text, typing
  indicators, read receipts, reply threading, audio/video rejection, oversized-file rejection and
  download-failure messages.
- Per-handler `GET /health` routes: already shadowed by the app-level route
  (`api/http.py:59-61`), so removing them changes no response.
- `ConversationThreadManager.store_attachments`'s signature, return type and error messages.
- `deployment/aws/*` runners (`ECSAgentRunner`, `ECSOutputConsumer`, `ServerlessAgentRunner`).

---

## Error handling

| Failure | Surface | Behaviour |
|---|---|---|
| Signature/secret verification fails | Edge | `HTTPException(403)`, warning log, no parse, no enqueue |
| Teams activity unauthenticated | Edge | `HTTPException(401)` from `process_activity`'s `PermissionError` (`teams_chat.py:120-122`) |
| Body is not valid JSON | Edge | `HTTPException(400)` (Teams' current behaviour, `teams_chat.py:114-116`), generalized |
| Delivery legitimately ignored | Edge | Success response, no enqueue, debug log |
| Attachment download fails | Edge | The platform's existing user-facing message; no enqueue for that message |
| Attachments present with `multimodal.enabled: false` or `storage_type: session_cache` | Edge | `ValueError` from `offload_attachments` → 500 and the actionable message in the log |
| `reply_context` over 8 KB serialized | Edge (`IntegrationProducer`) | `ValueError` naming the adapter, before the transport client |
| Enqueue fails | Edge | 5xx to the platform so it retries; nothing acknowledged to the user beyond the ack already sent |
| Unknown adapter name / unimportable dotted path | `IntegrationAdapterFactory` | `AKConfigError` at construction |
| Missing optional dependency for a built-in adapter | `IntegrationAdapterFactory` | `ImportError` naming the extra, via `require_extra` (`core/util/factory.py:49-64`) |
| Adapter host mounted outside a pipeline topology | `RESTAPI.run` | `AKConfigError` naming `IOHandler.run(handlers=[...])` |
| `PollerRunner.run` on the `in_memory` transport | `PollerRunner.run` | `AKConfigError` naming `IOHandler(pollers=[...])` |
| Pollers passed to `IOHandler` on a broker transport | `IOHandler.run` | Warning naming `PollerRunner.run(adapter)`; pollers not started |
| Output message names an adapter that cannot be resolved | Response Handler | `AKConfigError` from the factory propagates → `ConsumerLoop` retries → `on_permanent_failure`; the message never silently disappears, and the `integration` attribute value is named in the error log |
| `deliver` raises | Response Handler | Propagates; retried up to `output.max_receive_count`, then `on_permanent_failure` → `deliver_error` |
| `deliver_error` raises inside `on_permanent_failure` | Response Handler | Caught and logged by the method's existing `except Exception` (`response_handler.py:107-108`) |
| Poll iteration raises | `PollerRunner` | Logged; the loop continues after the interval |
| Response store cannot stream chunks | `AGUIPipelineRequestHandler.__init__` | `AKConfigError` naming the configured store and the supported ones (design §15.7); before the first request |
| AG-UI mounted outside a pipeline topology | `RESTAPI.run` | `AKConfigError` on `requires_pipeline`, as for the webhook host |
| A run's chunks stop arriving | Edge `_events_from_store` | `TimeoutError` from `store.stream` after `retry_count * delay` → one `RunErrorEvent`, then the generator returns |
| The run fails in the runner | Runner → edge | The error `StreamChunk` reaches the store as a chunk and becomes one `RunErrorEvent` |
| The run exhausts its retries | `ResponseHandler.on_permanent_failure` | The existing error chunk (`response_handler.py:92-101`) becomes one `RunErrorEvent`; the client never hangs |
| Client disconnects mid-stream | Edge | `close_stream` in the generator's `finally` releases the parked reader and drops the chunk key |
| AG-UI over a broker with `session.type: in_memory` | `AGUIPipelineRequestHandler.__init__` | `AKConfigError` naming `session.type` (design §15.7). `_SessionStoreConfig.type` defaults to `"in_memory"` (`core/config.py:94-96`), so this is the accidental default, and it silently costs the client's inbound `state`/`forwardedProps`: the runner would load a session the edge never shared. Checked only for the literal `in_memory` on a broker transport — a dotted-path BYO store cannot be classified and is left to the deployer |

**Exception scope.** Every `except` introduced here names its type: `HTTPException` for edge
rejections, `ValueError` for the offload guards and the budget check, `AKConfigError` for
resolution failures, `ImportError` for missing extras. The only bare `except Exception` is the one
already present in `ResponseHandler.on_permanent_failure` and the poll-loop guard that reproduces
`gmail_chat.py:135-141`. Adapters must not swallow platform-API failures inside `deliver`:
raising is what buys the retry.

**Concurrency.** `IntegrationProducer` and `RequestProducer` are used from FastAPI worker threads
(webhook) and the poller thread; both hold only a `QueueTransport`, whose `send` is already
documented as safe from any thread (`transport/base.py:10`). `IntegrationAdapterFactory`'s
instance cache is populated from `ResponseHandler` consumer threads, so it is guarded by a
`threading.Lock` — a double-construct would open two Slack SDK clients. Outbound adapters are
therefore shared across consumer threads and must keep no per-message state on `self`; the ABC
docstring states this. Each `deliver` call runs on its own event loop (`run_async_sync` →
`asyncio.run` in a thread with no loop), so an adapter holding an `httpx.AsyncClient` on `self`
would bind it to a dead loop — built-in adapters construct their client per call, as every
current `_send_message` already does (`whatsapp_chat.py:326`, `telegram_chat.py:249`,
`messenger_chat.py:331`, `instagram_chat.py:344`).

**Per-operation cost.** The edge gains one queue send per message (previously: none) and the
outbound side gains one factory lookup per output message (cached). The agent run itself moves
from one process to another; total work is unchanged apart from the JSON round-trip of the
`requests` list. Attachment bytes make one extra hop — into the `AttachmentStore` at the edge and
out again in the runner — replacing a base64 copy through the queue body that would not have fit
inside SQS's 256 KB message cap at all.

---

## Testing

Run with `cd ak-py && uv run pytest tests/<file>`.

### New test files

| File | Asserts |
|---|---|
| `tests/test_integration_adapter_contract.py` | `IntegrationAdapterContract` (the `QueueTransportContract` / `SandboxProviderContract` pattern, `pipeline/testing.py:20-28`) subclassed once per built-in adapter: `verify` rejects a bad signature with the platform's status; `parse` of an ignorable delivery returns an empty request list; `session_id` and `request_id` match the table in §9; `name` resolves through the factory; `reply_context` is flat, string-valued and inside the 8 KB budget; a full round-trip through `IntegrationProducer` → `QueueMessage` → `ResponseHandler` reaches `deliver` with the identical `reply_context` |
| `tests/test_integration_adapter_factory.py` | Built-in resolution; `outbound_adapter` dotted-path override per platform; dotted path for an unknown name; `AKConfigError` for an unknown bare name; `ImportError` naming the extra; instance caching |
| `tests/test_integration_producer.py` | Attributes stamped (`request_id`, `integration`, `reply_` prefix); no `user_id` attribute; `group_id == session_id`, `dedup_id == request_id`; body dump equals the REST path's; `ValueError` naming the adapter over the 8 KB budget |
| `tests/test_integration_webhook_handler.py` | Route mounting (POST + optional GET challenge); `verify` rejection short-circuits before enqueue; empty parse result → success response and no enqueue; enqueue failure → 500; `acknowledge`'s return value merged into `reply_context`; SDK-owned `response` returned verbatim; `requires_pipeline is True` |
| `tests/test_integration_poller_runner.py` | `run()` rejects `in_memory`; the loop enqueues, calls `mark_handled`, and exits on `ThreadRunner.shutdown_event` within one interval; a raising `poll` does not kill the loop |
| `tests/test_integration_roundtrip.py` | End-to-end over `InMemoryTransport` in the single-process topology: a fake platform event through `WebhookRESTRequestHandler` → `AgentRunner` (dummy agent, the `test_pipeline_request_handler.py` pattern) → `ResponseHandler` → a recording outbound adapter, asserting the reply text and reply context; plus the ≥ 400 path reaching `deliver_error` |
| `tests/test_messenger_integration.py`, `tests/test_instagram_integration.py`, `tests/test_telegram_integration.py` | New files — these three platforms have **no** test file today. Parse (text, postback, attachment, echo/ignore) and deliver (chunking at 2000/1000/4096, typing indicators, mark-seen) |
| `tests/test_attachment_offload.py` | `offload_attachments` rewrites image/file requests to refs in place, keeps other requests in order, raises the caller's message when multimodal is disabled, and rejects `session_cache` |
| `tests/test_agui_pipeline.py` | Construction: `requires_pipeline is True`; `AKConfigError` on a non-chunk-streaming store naming it; `AKConfigError` on `session.type: in_memory` over a broker; no raise on `in_memory` transport. Edge: the session is stored *before* the enqueue; the message carries `agui="1"`, `group_id == thread_id`, `dedup_id == request_id`, no `user_id` attribute, and `body.requests` prebuilt with `prompt == ""`; `RunStarted` is yielded before any store read; the 404/400/422 gates behave exactly as the direct handler's (same `_prepare`). Drain: chunks map through `AGUIMapper` in order; `{"agui_state": …}` becomes one `StateSnapshotEvent` and its absence yields none; an error chunk, a `TimeoutError` and an unexpected exception each produce exactly one `RunError` and no `RunFinished`; a clean drain ends with exactly one `RunFinished`; `close_stream` is called on every exit path including client disconnect |
| `tests/test_response_store_chunk_stream.py` | The chunk-streaming contract, parameterised over `in_memory`, `redis` and `valkey` (the latter two on fake clients, the `test_response_store_*` pattern): in-order delivery; `stream` stops on `done`; `close_stream` releases a parked reader; a timeout raises `TimeoutError`; the chunk key is deleted when the stream ends and by `delete_message`; `add_chunk` applies the TTL. Plus `DynamoDBResponseStore.supports_chunk_streaming() is False` and its `add_chunk` raising `NotImplementedError` |
| `tests/test_driver_redis_like.py` | `blpop` returns the decoded value, `None` on timeout, and floors a non-positive timeout to 1 s (asserted on the fake client's recorded call) — added to the existing driver test file if one exists, new otherwise |

### Rewritten test files

`tests/test_slack_integration.py`, `tests/test_whatsapp_integration.py`,
`tests/test_teams_integration.py` and `tests/test_gmail_integration.py` are rewritten, not edited:
their subject class is deleted and both of their anchors disappear. All ten Slack tests build the
handler with `object.__new__(AgentSlackRequestHandler)` and drive `handler.handle(body, say)` with
a `FakeChatService` patched onto `handler._chat_service` (`test_slack_integration.py:48-58`,
`:70-76`); the Gmail tests drive `handler._process_with_agent` the same way
(`test_gmail_integration.py:28-52`). After this change there is no `_chat_service` on an adapter
at all. The rewrites keep every assertion that is about platform behaviour (prompt text, session
id, request composition, chunking, rejection messages) and move it onto `parse`/`deliver`.

### Changed test files

| File | What changes |
|---|---|
| `tests/test_pipeline_agent_runner.py` | `_input_msg` gains cases with `integration` and `reply_*` attributes: assert both classes of attribute are forwarded to the output message and the existing three still are; assert `StreamAgentRunner.process` and `.on_permanent_failure` delegate to the non-streaming path when `ATTR_INTEGRATION` is present; assert `body.requests` is passed to `process_chat_request`. Plus for §15: a plain `AgentRunner` streams an `ATTR_AGUI` message under `mode: rest_sync` (fans out one output message per chunk, not one response); `agui` is forwarded to every output message; the `user_id` guard does **not** fire for an `ATTR_AGUI` message on a broker transport but still fires without the marker; a state change emits one `{"agui_state": …}` chunk after the last content chunk and no chunk when the state is unchanged |
| `tests/test_pipeline_response_handler.py` | The integration branch precedes the mode branch (a message with `integration` reaches `deliver` under every `ExecutionMode`); status ≥ 400 reaches `deliver_error` with `ERROR_MESSAGE`, not the raw error; `on_permanent_failure` reaches `deliver_error`; a `deliver` failure propagates. Uses the existing `_use_mode` monkeypatch helper (`:22-30`). Plus: an `agui` message reaches `_store_chunk` under every `ExecutionMode` — including `rest_sync`, where today's path would have stored a whole response — and does so with no `user_id` attribute present |
| `tests/test_pipeline_request_handler.py` | Assert `RestHandler._enqueue_request`'s envelope is unchanged after the `RequestProducer` delegation (body dump, attributes, group/dedup ids) and that `get_transport()` is still the injection point |
| `tests/test_pipeline_io_handler.py` | `pollers` co-hosted as a peer thread on `in_memory`; not started (with a warning) on a broker transport |
| `tests/test_api_http.py` | `RESTAPI.run` raises `AKConfigError` for a `requires_pipeline` handler, on `RESTAPI` and on a subclass; the no-handlers delegation path still reaches `IOHandler` unchanged |
| `tests/test_config.py` | The seven `outbound_adapter` fields exist with `default=""` and existing fields are unchanged |
| `tests/test_model.py` | `BaseRunRequest.requests` round-trips every `AgentRequest` variant through `model_dump`/`model_validate`, including `AgentRequestAttachmentRef` |
| `tests/test_chat_service_core.py` | `process_chat_request(req, requests=[...])` forwards the prebuilt list and skips `RequestBuilder` |

The riskiest consumer is `ResponseHandler`: it gains a branch ahead of every existing delivery
path, and its test file is listed above.
