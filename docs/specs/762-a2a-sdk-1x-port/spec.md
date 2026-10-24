# #762: Port the A2A surface to a2a-sdk 1.x, and send structured replies as data parts — Implementation Spec

This spec details how the approved [design](design.md) is built. Four source files change
(`api/a2a/a2a.py`, `api/a2a/handler.py`, `core/builder.py`, `a2ui/hook.py`), plus the pin, two
example clients, tests and docs. The one-sentence idea: keep every Agent Kernel class and the #780
queue path as they are, and swap only what touches the SDK — the card's fields, the route factory,
the reply helpers and the error types — so the change is a port, not a redesign.

All 1.x behaviour quoted here was run on **a2a-sdk 1.2.3** in a scratch venv on 2026-10-24
(see [Evidence](#evidence)). Code citations are to this branch at `f804754a`.

---

## Design

### 1. Dependency (`ak-py/pyproject.toml`, examples)

- `ak-py/pyproject.toml:185`: `"a2a-sdk[http-server]>=0.3.6,<1"` → `"a2a-sdk[http-server]==1.2.3"` (D5).
- `ak-py/uv.lock`: `uv lock --upgrade-package a2a-sdk` (today resolves 0.3.26, `uv.lock:19-20`).
  - 1.2.3's `http-server` extra brings `starlette` and `sse-starlette`, which `create_rest_routes`
    needs. No `grpc` is needed: 1.0.0 failed `import a2a.server.routes` without it, 1.1.2+ does not.
- `examples/k8s/openai-queue-mode/pyproject.toml:9`: same exact pin; re-lock (its lock has 0.3.26).
- `examples/api/a2a/multi/uv.lock:11-12` (0.3.6): the example's `pyproject.toml` has no direct pin,
  so `uv lock --upgrade-package a2a-sdk` moves it.
- The six framework extras are unchanged: none imports `a2a`.

### 2. Card builder (`A2ACardBuilder`, `core/builder.py:19-48`)

`build` keeps its name and keyword signature, so the five adapters that call it
(`openai.py:1091`, `crewai.py:523`, `langgraph.py:401`, `smolagents.py:319`, `pydanticai.py:886`)
do not change. It becomes a `classmethod` so it can reach its helpers.

```python
class A2ACardBuilder(Builder):
    PROTOCOL_BINDING = "HTTP+JSON"   # REST only, as today
    PROTOCOL_VERSION = "1.0"         # the only interface served (D1)
    TEXT_MODE = "text/plain"         # D4

    @classmethod
    def build(cls, name: str, description: Any, skills: list[Any]) -> Any:
        """A 1.x AgentCard: one 1.0 interface, media-type modes, the A2UI extension when in scope."""

    @classmethod
    def _description(cls, name: str, description: Any) -> str:
        """`description` when it is a str; otherwise "" and a warning naming the agent."""

    @staticmethod
    def _tag_untagged(name: str, skills: list[Any]) -> list[Any]:
        """Each skill with empty `tags` gets `[name]`; skills with tags are left alone."""
```

`build` produces:

| Field | Value | Today |
|---|---|---|
| `name`, `version`, `skills` | unchanged sources (`library_version`; skills after `_tag_untagged`) | same |
| `description` | `_description(name, description)` | raw value (`builder.py:40`) |
| `supported_interfaces` | `[AgentInterface(url=f"{a2a.url}/{name}", protocol_binding="HTTP+JSON", protocol_version="1.0")]` | `url=` (`:41`), `preferred_transport=` (`:45`) |
| `default_input_modes` | `["text/plain"]` | `["text"]` (`:43`) |
| `default_output_modes` | `["text/plain"]`, plus `A2UIPostHook.MEDIA_TYPE` when in A2UI scope | `["json"]` (`:44`) |
| `capabilities` | `AgentCapabilities(streaming=False, extensions=[...])`, the extension only when in A2UI scope | `streaming=False` (`:46`) |

Rules:

1. **A2UI scope is asked of `a2ui/`, never re-derived.** `build` calls
   `A2UIPostHookFactory.labels(name)` (§3). True → append the media type to the output modes and
   `AgentExtension(uri=A2UIPostHook.EXTENSION_URI, required=False)` to `capabilities.extensions`.
   The import is inside `build`, beside the existing lazy `a2a.types` import: `a2ui.hook` imports
   `core.base`/`core.config`/`core.hooks`/`core.model`, so a module-scope import from
   `core/builder.py` risks an import cycle through `core/__init__`.
2. **No `tenant` on the interface.** Multi-tenant routes are a non-goal, and an empty tenant
   serialises as an absent key.
3. **`_tag_untagged` mutates the protobuf skill in place** (`skill.tags.append(name)`); `AgentSkill`
   is a protobuf message, so there is no model copy to make. Adapters keep passing `tags=[]`.
4. **`_description` warns once per build, not per request.** Cards are built once per process
   (`A2A._build`, `api/a2a/a2a.py:118-131`). Today OpenAI passes `self.agent.instructions`
   (`openai.py:1091`), which may be a callable; 1.x raises `TypeError` on it.

### 3. A2UI scope and extension URI (`a2ui/hook.py`)

These additions keep `a2ui/` the only package that names A2UI (design §5), and one rule decides both
labelling and the card.

```python
class A2UIPostHook(PostHook):
    MEDIA_TYPE = "application/a2ui+json"                            # unchanged (:34)
    EXTENSION_URI = "https://a2ui.org/a2a-extension/a2ui/v0.9.1"    # new (D6): an identifier, not a page

    @classmethod
    def a2a_data(cls, media_type: str, content: Any) -> Any:
        """What an A2A data part carries (D8): an A2UI dict -> [dict]; a list, or any other media type, as is."""

    @staticmethod
    def scopes(agent_name: str) -> bool:
        """True when `a2ui.agents` is unset or names this agent (today's `_applies_to` rule, by name)."""

    @staticmethod
    def _applies_to(agent: Agent) -> bool:
        """Unchanged contract; now `return A2UIPostHook.scopes(agent.name)`."""


class A2UIPostHookFactory:
    @classmethod
    def labels(cls, agent_name: str) -> bool:
        """Whether this agent's JSON replies get labelled: `a2ui.enabled` and `scopes(agent_name)`.

        Same fallback as `get()`: any exception logs and returns False, so a broken a2ui block
        never fails the A2A mount.
        """
```

- `EXTENSION_URI` is the v0.9.1 binding's identifier, defined at
  `https://a2ui.org/specification/v0.9.1-a2ui-extension-specification/`; it does not resolve as a
  page (404) by design.
- `a2a_data` holds the binding's "data MUST be an array of messages" rule in `a2ui/`, so the
  executor applies it without naming A2UI. Only the A2A executor calls it; no other surface's shape
  changes.
- `_applies_to` keeps its name and signature (no test patches it today; it stays the hook's call
  site at `hook.py:45`).
- `labels` deliberately ignores `execution.mode`. `get()` warns that the hook never runs on a
  streamed run (`hook.py:115-120`), but an A2A request never streams: `StreamAgentRunner` hands a
  `PROTOCOL` message to the single-reply path (`_wants_single_reply`), which goes through
  `Runtime.run`, where the hook does run. So the card's claim holds in every mode.

### 4. Executor (`A2A.Executor`, `api/a2a/a2a.py:52-103`)

Imports (`a2a.py:1-10`):

```python
from a2a.helpers import new_data_message, new_text_message   # was a2a.utils.new_agent_text_message
from a2a.types import AgentCard, InternalError, Message, UnsupportedOperationError
# removed: from a2a.utils.errors import ServerError

from ...a2ui.hook import A2UIPostHook   # a2a_data only; a2ui imports core, never api
```

`a2a.server.agent_execution`, `a2a.server.events.EventQueue` and
`a2a.server.tasks.{InMemoryTaskStore, TaskStore}` keep their 0.3 paths on 1.2.3.

```python
class Executor(AgentExecutor):
    ERROR_MESSAGE = "Sorry, Agent Kernel encountered an error while processing your request"  # unchanged
    TIMEOUT_MESSAGE = "Timed out waiting for the agent's reply"                                # unchanged

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        """Checks and request as today; one reply message, or raise InternalError."""

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise UnsupportedOperationError()

    @classmethod
    def _as_message(cls, reply: "QueuedReply", context: RequestContext) -> Message:
        """A data part for a labelled dict/list result; one text part for everything else."""

    @staticmethod
    def _as_text(result: Any) -> str:  # unchanged (:100-103)
```

`execute`, step by step:

1. Context checks and the `BaseRunRequest` body: unchanged (`a2a.py:70-77`).
2. `ReplyTimeoutError` → log as today (`:79`), then `raise InternalError(message=TIMEOUT_MESSAGE) from e`.
3. Any other exception → `log.exception` as today (`:83`), then `raise InternalError(message=ERROR_MESSAGE) from e`.
4. `reply.is_error or reply.result is None` → log as today (`:88`), then `raise InternalError(message=ERROR_MESSAGE)`.
5. Success → `await event_queue.enqueue_event(self._as_message(reply, context))`.

`_as_message` mapping (D3, D7, D8):

| `reply.media_type` | `reply.result` | Message |
|---|---|---|
| set | `dict` or `list` | `new_data_message(A2UIPostHook.a2a_data(media_type, result), media_type=media_type, context_id=..., task_id=...)`, then `parts[0].metadata["mimeType"] = media_type` |
| set | anything else | `new_text_message(_as_text(result), context_id=..., task_id=...)` |
| unset | any | `new_text_message(_as_text(result), context_id=..., task_id=...)` |

Rules:

1. **`context_id` and `task_id` are always passed by keyword.** 1.x's
   `new_text_message(text, media_type=None, context_id=None, task_id=None, ...)` puts `media_type`
   second; the 0.3 call shape `new_agent_text_message(text, context_id, task_id)` (`:92`, `:98`)
   ported positionally would send the context id as the media type.
2. **No media type on a text part.** The text helper's `media_type` stays unset, as today.
3. **The executor never names A2UI.** It maps whatever `media_type` the body carries
   (`QueuedReply.media_type`, `pipeline/request_client.py:43-45`), passes every labelled payload
   through `A2UIPostHook.a2a_data`, and writes the label in both `media_type` and
   `metadata["mimeType"]` for every media type (D7).
4. **`_send_error` is deleted** (`:97-98`). On 1.x an event enqueued before the raise is never
   delivered (verified: the caller gets only the error), so the error's own `message` is what the
   caller reads. Details stay in the log only; the message text is fixed, never the exception's.

`A2A` class (`a2a.py:21-157`), one change in `_build` (`:118-131`): a `None` card is skipped with
`_log.warning(f"Agent '{name}' has no A2A card; it is not served over A2A")` and not stored. Google
ADK returns `None` (`adk.py:1519-1524`). Everything else in the class — `PROTOCOL`, `get_client`,
`get_executor`, `get_cards`, `get_card`, `get_agent_names`, `get_task_store`, `RedisTaskStore`
(`:160-161`) — is unchanged.

### 5. Routes (`A2ARESTRequestHandler`, `api/a2a/handler.py`)

```python
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.request_handlers.response_helpers import agent_card_to_dict
from a2a.server.routes import create_agent_card_routes, create_rest_routes
from starlette.routing import BaseRoute, Route


class A2ARESTRequestHandler:
    @classmethod
    def get_catalog_router(cls) -> APIRouter:
        """GET /a2a/catalog -> {"cards": [agent_card_to_dict(card), ...]}"""

    @classmethod
    def get_agent_routers(cls) -> List[APIRouter]:
        """One APIRouter per served agent at /a2a/{agent}: the 1.0 REST routes plus its card route."""

    @classmethod
    def _add_route(cls, router: APIRouter, route: BaseRoute) -> None:
        """Re-register one SDK Starlette Route on the router; skip anything that is not a Route."""
```

Per agent, `get_agent_routers` builds:

```python
card = A2A.get_card(agent)
request_handler = DefaultRequestHandler(
    agent_executor=A2A.get_executor(agent),
    task_store=A2A.get_task_store(),
    agent_card=card,                       # required on 1.x
)
router = APIRouter(prefix=f"/a2a/{agent}")
for route in [*create_rest_routes(request_handler), *create_agent_card_routes(card)]:
    cls._add_route(router, route)
```

Rules:

1. **`enable_v0_3_compat` is left at its default `False`** (D1), so `/a2a/{agent}/v1/...` is never
   mounted and answers 404.
2. **`_add_route` re-registers only `starlette.routing.Route`**, with
   `router.add_api_route(route.path, route.endpoint, methods=...)`, dropping `HEAD` from the
   methods (Starlette adds it beside `GET`; FastAPI would register a duplicate operation id — the
   SDK's own `add_a2a_routes_to_fastapi` drops it for the same reason). The `Mount('/{tenant}')`
   that `create_rest_routes` appends is skipped with a debug log: multi-tenant routes are a non-goal.
3. **Not `add_a2a_routes_to_fastapi`.** It takes a whole `FastAPI` app and appends un-prefixed
   routes; the per-agent `/a2a/{agent}` prefix needs an `APIRouter`, which `RESTAPI.build_app`
   already collects (`api/http.py:190-194`, unchanged).
4. **The card route is the SDK's** (`create_agent_card_routes(card)`, path
   `/.well-known/agent-card.json` = `AGENT_CARD_WELL_KNOWN_PATH`), which serialises through
   `agent_card_to_dict` and adds an `ETag`. The hand-written dynamic `card_router`
   (`handler.py:67-75`) is deleted, so an unknown agent has no route and gets 404 instead of
   `None.model_dump()` (`:72-73`).
5. **The catalog uses the same serialiser** (`agent_card_to_dict`), replacing `c.model_dump()`
   (`:44`). With only a `1.0` interface, `agent_card_to_dict`'s compat step finds no 0.3 interface
   and adds no `url`/`preferredTransport` keys.
6. `agent_card_to_dict` is imported from its defining module: 1.2.3 does not re-export it from
   `a2a.server.request_handlers`. The exact pin (D5) makes that safe; a pin bump re-runs the tests.
7. The class docstring's route list (`handler.py:14-31`) is rewritten to the 1.0 routes.

Mounted per agent after the change:

| Method | Path under `/a2a/{agent}` |
|---|---|
| POST | `/message:send`, `/message:stream`, `/tasks/{id}:cancel` |
| GET, POST | `/tasks/{id}:subscribe` |
| GET | `/tasks`, `/tasks/{id}`, `/tasks/{id}/pushNotificationConfigs`, `/extendedAgentCard`, `/.well-known/agent-card.json` |
| GET, DELETE | `/tasks/{id}/pushNotificationConfigs/{push_id}` |
| POST | `/tasks/{id}/pushNotificationConfigs` |

`message:stream` stays refused by the SDK because the card declares `streaming: false`, as today.

### Consumer changes

- **Framework adapters** (`openai`, `crewai`, `langgraph`, `smolagents`, `pydanticai`): no code
  change. `AgentSkill(id, name, description, tags=[])` builds on 1.x as is; tags are filled by the
  builder. Verified unchanged: each still calls `A2ACardBuilder.build(name=, description=, skills=)`.
- **Google ADK** (`adk.py:1519-1524`): no change; its `None` card is now skipped with a warning.
- **`RESTAPI.build_app`** (`api/http.py:190-194`): unchanged; still mounts the catalog router and
  the per-agent routers when `a2a.enabled`.
- **`RESTAPI` / `IOHandler` / `ECSIOHandler` refusal and fail-fast rules (#780)**: unchanged.
- **Example clients** move to the 1.x client API. A 1.x request must carry `A2A-Version: 1.0`
  (without it the server reads 0.3 and answers 400); `ClientFactory` sets that header on the
  `httpx` client, a hand-built `RestTransport` does not.
  ```python
  # Card URL is reachable (multi example, and the round-trip test with a2a.url pointed at it):
  client = ClientFactory(ClientConfig(streaming=False, httpx_client=http, supported_protocol_bindings=["HTTP+JSON"])).create(card)

  # Card URL is not reachable (k8s example behind a port-forward on any port): keep the explicit
  # URL, and set the header the factory would have set.
  http = httpx.AsyncClient(timeout=120, headers={VERSION_HEADER: PROTOCOL_VERSION_CURRENT})  # a2a.utils.constants
  client = BaseClient(card, ClientConfig(streaming=False), RestTransport(http, card, url=agent_url), interceptors=[])

  request = SendMessageRequest(message=Message(message_id=..., context_id=..., role=Role.ROLE_USER, parts=[Part(text=text)]))
  async for item in client.send_message(request):   # yields StreamResponse
      if item.HasField("message"):
          text = get_message_text(item.message)    # from a2a.helpers
  ```
  - `examples/api/a2a/multi/client.py:4-53` (`A2AHttpClient.send`).
  - `examples/k8s/openai-queue-mode/protocol_client.py:15-37` (`ask_a2a`).

### Docs (design §8)

- `docs/docs/api/a2a-server.md:85-95`: the route table lists the 1.0 routes from §5 (no `/v1/`);
  the paragraph after it says a labelled reply is a data part carrying its media type (numbers as
  doubles), and an unlabelled one is text.
  - A short "Migrating from A2A 0.3" note: new paths, a 1.x client (`a2a-sdk>=1`) sending
    `A2A-Version: 1.0`, the card's camelCase shape and `supportedInterfaces`.
- `docs/docs/advanced/a2ui.md:82`: the A2A row becomes "yes, as a data part with `mediaType`; the
  card declares the A2UI extension".

### Config changes

None (design §6).

- Card URLs reuse `a2a.url`; served agents reuse `a2a.agents`; the extension and the extra output
  mode reuse `a2ui.enabled` and `a2ui.agents`; `a2a.task_store_type` is untouched.
- No switch for 0.3 clients (D1). Existing YAML and `AK_A2A__*` / `AK_A2UI__*` env vars keep their
  meaning; field descriptions in `_A2AConfig` (`core/config.py:139-143`) and `_A2UIConfig`
  (`:875-886`) are unchanged.

### Behavioural changes

All intentional.

1. **0.3 clients are not served** (D1). `/a2a/{agent}/v1/...` → 404. A 0.3-shaped request sent to
   a 1.0 route without an `A2A-Version: 1.0` header → **400 `FAILED_PRECONDITION`** ("A2A version
   '0.3' is not supported"), because 1.x treats a missing header as 0.3.
2. **Card JSON changes shape**: protobuf JSON (camelCase), 1.0 fields only, no `url` /
   `preferredTransport`. Hand-written `/a2a/catalog` readers must update.
3. **Card modes are media types** (D4): `text/plain` in and out, plus `application/a2ui+json` out
   for agents in A2UI scope.
4. **The card declares the A2UI v0.9.1 extension** for agents in A2UI scope (`required: false`, D6).
5. **Untagged skills carry `[<agent name>]`**, so 1.x stops warning "not spec-compliant" on each
   card serialisation.
6. **A non-string `description` becomes `""` with a warning**, instead of failing the A2A mount.
7. **An agent with no card is not served** (warning), instead of being stored as `None` and making
   `/a2a/catalog` call `None.model_dump()` (`handler.py:44`).
8. **An unknown agent's well-known card → 404**, not 500; the card route now sends an `ETag`.
9. **A labelled reply is a data part** (`{"data": ..., "mediaType": ..., "metadata": {"mimeType": ...}}`),
   not JSON text. The label is in both places (D7).
   - An A2UI object arrives as a one-item list (D8), on A2A only; a list, or a payload with any
     other media type, keeps its shape.
   - Numbers ride as protobuf `Value` doubles: an integer `1` arrives as `1.0` in a Python 1.x
     client, and an integer above 2^53 loses precision. JSON text never had this limit; it is the
     protocol's data-part encoding, not an Agent Kernel choice. A JavaScript client sees no
     difference for safe integers.
10. **A failure sends no text message.** The caller reads one error, 500 `INTERNAL`, whose message
    is `ERROR_MESSAGE` (timeout: `TIMEOUT_MESSAGE`). Today it read a text message carrying
    `ERROR_MESSAGE` plus an `InternalError` whose message was the SDK default `"Internal error"`.
11. **a2a-sdk is pinned to `==1.2.3`** (D5): any other version beside `agentkernel[a2a]` no longer
    resolves.

**Non-changes:**

- The #780 queue path: body (`BaseRunRequest(prompt, agent, session_id=context_id)`),
  `protocol="a2a"`, wait budget, `QueueRequestClient` reuse, lazy `pipeline` import.
- Unlabelled replies (text, image text, structured without a `media_type`) leave exactly as today.
- Class and module names: `A2A`, `A2A.Executor`, `A2ARESTRequestHandler`, `A2ACardBuilder`,
  `RedisTaskStore`; `A2A.PROTOCOL`, `ERROR_MESSAGE`, `TIMEOUT_MESSAGE` values.
- `A2ACardBuilder.build(name, description, skills)` call shape; `Agent.get_a2a_card() -> Any`
  (`core/base.py:686`).
- `/a2a/catalog` and `/a2a/{agent}/.well-known/agent-card.json` paths.
- `A2UIPostHook` labelling behaviour and `MEDIA_TYPE`.
- Session data: nothing A2A writes to a session or the response store changes, so data written
  before the change reads back identically.

## Error handling

| Failure | Where | What surfaces |
|---|---|---|
| `a2a-sdk` not installed, `a2a.enabled` | `api/http.py:191` lazy import | `ImportError` at app build, as today |
| Card build raises (adapter bug) | `A2A._build` | propagates and fails the mount, as today |
| Non-string description | `A2ACardBuilder._description` | warning; card built with `""` |
| `get_a2a_card()` returns `None` | `A2A._build` | warning; agent not served |
| `a2ui` block broken | `A2UIPostHookFactory.labels` | logged; returns False (no extension) |
| Reply timeout | `Executor.execute` | 500 `INTERNAL`, message `TIMEOUT_MESSAGE`; request id in log |
| Error status / missing result / any exception | `Executor.execute` | 500 `INTERNAL`, message `ERROR_MESSAGE`; details in log only |
| `cancel` | `Executor.cancel` | `UnsupportedOperationError` (SDK maps it to its status) |
| 0.3 client | SDK | 404 on `/v1/...`; 400 on a 1.0 route without the version header |

- **Exception scope** is unchanged from #780: `ReplyTimeoutError` first, then bare `Exception`.
- **Concurrency**: no new shared state. Cards are built once at app build; the executor holds
  none per request; `A2UIPostHookFactory.labels` reads config per call, like `_applies_to`.
- **Per-operation cost**: a labelled reply pays one dict → protobuf `Struct` conversion inside
  `new_data_message`, proportional to the payload. Nothing else is added to the request path.

## Testing

### Changed files

**`tests/test_api_a2a.py`** (executor, #780 rows kept, ported):

- Imports: `Message, Part, Role, SendMessageRequest` from `a2a.types`; `get_message_text`,
  `get_data_parts` from `a2a.helpers`; `ServerCallContext` from `a2a.server.context`;
  `InternalError, UnsupportedOperationError` from `a2a.types`. `ServerError` is gone.
- `_context()`: `RequestContext(ServerCallContext(), request=SendMessageRequest(message=Message(..., role=Role.ROLE_USER, parts=[Part(text=text)])), task_id=..., context_id=...)`.
- `EventQueue` is abstract on 1.x (only `enqueue_event`): a `RecordingEventQueue(EventQueue)`
  double collects events; `_execute` returns `(events, raised A2AError | None)`.
- `TestReplies`: text and image rows unchanged; `AgentReplyAny(content={"a": 1})` (no label) stays
  text `'{"a": 1}'`; the labelled rows move to a new `TestDataParts`.
- New `TestDataParts`: a labelled list is one data part with `media_type` and
  `metadata == {"mimeType": ...}`; an A2UI object arrives as `[object]`; another media type keeps
  its object and still carries both labels; `1` arrives as the float `1.0`.
- `TestFailures`: `events == []` and `raised.message == ERROR_MESSAGE` (timeout: `TIMEOUT_MESSAGE`);
  log assertions unchanged. `cancel` raises `UnsupportedOperationError`.
- New: positional-argument guard — the text message's `context_id`/`task_id` equal the context's
  and its part has no `media_type`.

**`tests/test_protocol_pipeline_roundtrip.py`**:

- `_a2a_send` (`:142-157`): the `ClientFactory` client from [Consumer changes](#consumer-changes),
  with `AK_A2A__URL` set to the test's base URL so the card's interface is the one called; replies
  read from `item.message`.
- New: `POST /a2a/{agent}/v1/message:send` → 404.
- New: with `AK_A2UI__ENABLED=true` and a runner returning JSON text, the reply arrives through the
  queue as a data part with `mediaType: application/a2ui+json`. Reset `Runtime._system_post_hooks`
  to `None` before and after, since it is cached per class.

**`tests/test_cross_surface_parity.py`**: new `test_a2a_carries_the_same_pair` (executor over
the file's `_QueueClient`, data part content `== [EXPECTED_CONTENT]` — the A2A-only list of D8 —
media type `== MEDIA_TYPE`);
A2A joins `test_every_surface_agrees_on_the_payload`; the "A2A sits out" docstring (`:11-12`) goes.
The fixture's values are all strings after normalisation, so the double encoding does not affect it.

**`tests/test_a2ui_hook.py`**: `scopes` by name; `labels` false when disabled, false out of scope,
true in scope, false (and logged) when reading config raises; `_applies_to` agrees with `scopes`;
`EXTENSION_URI` is the v0.9.1 identifier; `a2a_data` wraps an A2UI object and returns a list or
another media type's payload as is.

**`tests/test_packaging_extras.py`**: the `a2a` extra is exactly `a2a-sdk[http-server]==1.2.3`.

### New file: `tests/test_api_a2a_surface.py`

- **Imports** (the regression the issue says CI never caught): `import agentkernel.api.a2a.a2a`
  and `import agentkernel.api.a2a.handler` succeed in a subprocess.
- **Card** (`A2ACardBuilder.build`, config monkeypatched): one `supported_interfaces` entry
  (`{a2a.url}/{name}`, `HTTP+JSON`, `1.0`); `agent_card_to_dict` has no `url` or
  `preferredTransport`; modes per D4; extension and A2UI output mode present only when `a2ui`
  enabled and in scope (enabled + `agents` naming another agent → absent); callable description →
  `""` + warning; empty tags → `[name]`, given tags kept.
- **Routes** (`RESTAPI.build_app(handlers=[])` over `httpx.ASGITransport`, a dummy agent): the 1.0
  route set exists; `/v1/message:send` → 404; well-known card → 200, camelCase, `ETag` header;
  unknown agent's card → 404; `/a2a/catalog` lists the same dicts; an agent whose card is `None` is
  absent from both, with the warning logged; no `/{tenant}` route mounted.

### Run

```bash
cd ak-py
uv run pytest tests/test_api_a2a.py tests/test_api_a2a_surface.py tests/test_a2ui_hook.py \
  tests/test_protocol_pipeline_roundtrip.py tests/test_cross_surface_parity.py tests/test_packaging_extras.py
uv run pytest            # full suite
```

## Evidence

<details>
<summary>▸ 1.2.3 behaviour verified for this spec (scratch venv, 2026-10-24)</summary>

- Signatures: `create_rest_routes(request_handler, context_builder=None, enable_v0_3_compat=False,
  path_prefix='', shutdown_grace_period=0) -> list[BaseRoute]`;
  `create_agent_card_routes(agent_card, card_modifier=None, card_url='/.well-known/agent-card.json',
  cache_control=None)`; `DefaultRequestHandler(agent_executor, task_store, agent_card, ...,
  validate_input_modes=False, ...)`; `new_text_message(text, media_type=None, context_id=None,
  task_id=None, role=ROLE_AGENT)`; `new_data_message(data, media_type=None, context_id=None, ...)`;
  `RequestContext(call_context, request=None, task_id=None, context_id=None, ...)`;
  `RestTransport(httpx_client, agent_card, url)`; `BaseClient(card, config, transport, interceptors)`.
- `create_rest_routes` returns 12 `Route`s plus `Mount('/{tenant}')`; `create_agent_card_routes`
  one `Route`. Re-registered on an `APIRouter(prefix="/a2a/triage")`: card 200 with `ETag`, unknown
  agent 404, `/v1/message:send` 404, `/message:send` without `A2A-Version` 400
  `FAILED_PRECONDITION`.
- Data reply on the wire: `"parts":[{"data":{"a":1.0},"mediaType":"application/a2ui+json"}]`
  (with D7's `metadata.mimeType` set: `{"data":[{"a":1.0}],"metadata":{"mimeType":"application/a2ui+json"},"mediaType":"application/a2ui+json"}`);
  `2**60` decodes as `1.152921504606847e+18`; a list payload stays a list.
- `raise InternalError(message=...)` in the executor → HTTP 500
  `{"error":{"code":500,"status":"INTERNAL","message":...}}`; the 1.x client raises
  `InternalError` with that message.
- `AgentCard(description=<callable>)` → `TypeError`. `tags=[]` → warning "AgentCard is not
  spec-compliant - REQUIRED fields missing or empty: skills[0].tags" on each `agent_card_to_dict`.
- `ClientFactory(ClientConfig()).create(card)` with a REST-only card raises "no compatible
  transports found" unless `supported_protocol_bindings=["HTTP+JSON"]`.
- `ClientFactory.__init__` sets `A2A-Version: 1.0` on its `httpx` client; a `BaseClient` over a
  hand-built `RestTransport` sends no version header and gets 400 `VersionNotSupportedError`
  (found porting the round-trip test, iteration 2).

</details>
