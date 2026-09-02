# #524: Pluggable request/response adapter for messaging integrations — Implementation Spec

Builds the `integration/adapter/` seam that `design.md` specifies: two ABCs (`InboundAdapter`,
`OutboundAdapter`) plus a normalized `InboundRequest` envelope, hosted by a generic
`WebhookRESTRequestHandler` (webhook platforms) and a `PollerRunner` (Gmail), producing into the
`agentkernel.pipeline` input queue and delivered from the Response Handler's new integration
dispatch branch. The seven `Agent<Platform>RequestHandler` classes and their `<platform>_chat.py`
modules are deleted; each `integration/<platform>/` gains an `adapter.py` holding the platform's
inbound/outbound pair. `design.md` is the requirements source; every section below traces back to
one of its numbered requirement sections.

Two requirements were revised while writing this spec and are marked for re-review in `design.md`
(§1 `parse`'s return type, §11 where the pipeline fail-fast is raised); both are reflected here.

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

Two new module-level constants beside the existing four (`envelope.py:8-11`):

```python
ATTR_INTEGRATION = "integration"      # presence marks a message as integration traffic
REPLY_CONTEXT_PREFIX = "reply_"       # every reply-to coordinate is stamped with this prefix
```

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

### 6. Response Handler dispatch — `pipeline/response_handler.py`

`process` gains one branch **before** the `execution.mode` branch (`:51-66`); a message without
`ATTR_INTEGRATION` takes today's path unchanged:

```python
def process(self, message: QueueMessage) -> None:
    integration = message.attributes.get(ATTR_INTEGRATION)
    if integration:
        self._deliver_integration(message, integration)
        return
    mode = AKConfig.get().execution.mode
    ...
```

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

Unchanged and verified: every non-integration `RESTRequestHandler`
(`AgentRESTRequestHandler`, `AgentThreadRequestHandler`, `ScheduleRESTRequestHandler`,
`AGUIRequestHandler`, `RequestHandler`) inherits `requires_pipeline = False` and is unaffected;
`ECSIOHandler` and the `deployment/aws` runners are untouched (design §13).

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
| `tests/test_pipeline_agent_runner.py` | `_input_msg` gains cases with `integration` and `reply_*` attributes: assert both classes of attribute are forwarded to the output message and the existing three still are; assert `StreamAgentRunner.process` and `.on_permanent_failure` delegate to the non-streaming path when `ATTR_INTEGRATION` is present; assert `body.requests` is passed to `process_chat_request` |
| `tests/test_pipeline_response_handler.py` | The integration branch precedes the mode branch (a message with `integration` reaches `deliver` under every `ExecutionMode`); status ≥ 400 reaches `deliver_error` with `ERROR_MESSAGE`, not the raw error; `on_permanent_failure` reaches `deliver_error`; a `deliver` failure propagates. Uses the existing `_use_mode` monkeypatch helper (`:22-30`) |
| `tests/test_pipeline_request_handler.py` | Assert `RestHandler._enqueue_request`'s envelope is unchanged after the `RequestProducer` delegation (body dump, attributes, group/dedup ids) and that `get_transport()` is still the injection point |
| `tests/test_pipeline_io_handler.py` | `pollers` co-hosted as a peer thread on `in_memory`; not started (with a warning) on a broker transport |
| `tests/test_api_http.py` | `RESTAPI.run` raises `AKConfigError` for a `requires_pipeline` handler, on `RESTAPI` and on a subclass; the no-handlers delegation path still reaches `IOHandler` unchanged |
| `tests/test_config.py` | The seven `outbound_adapter` fields exist with `default=""` and existing fields are unchanged |
| `tests/test_model.py` | `BaseRunRequest.requests` round-trips every `AgentRequest` variant through `model_dump`/`model_validate`, including `AgentRequestAttachmentRef` |
| `tests/test_chat_service_core.py` | `process_chat_request(req, requests=[...])` forwards the prebuilt list and skips `RequestBuilder` |

The riskiest consumer is `ResponseHandler`: it gains a branch ahead of every existing delivery
path, and its test file is listed above.
