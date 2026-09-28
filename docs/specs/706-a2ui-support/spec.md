# #706: structured replies carry their format, end to end — Implementation Spec

`AgentReplyAny` gains a `media_type` field and a JSON-safe `content`; every non-streaming exit point
emits `content` as an object when that field is set and the string it emits today when it is not; a
new `DataMessage` stream event carries the same pair mid-stream; and one small `a2ui` capability sets
the label from two config keys. Requirements come from [`design.md`](design.md) — this document is
how they are built, not whether. Where the two disagree, `design.md` is authoritative and this file
is wrong.

Code facts verified against `develop` at `80936df9`; paths are relative to
`ak-py/src/agentkernel/` unless stated. Protocol facts verified against
[a2ui.org](https://a2ui.org/) (September 2026): **v0.9.1 is Current, v1.0 is a release candidate**.

**Pluggability note, stated so a reviewer can confirm rather than flag it.** The house rule is ABC +
factory + dotted-path BYO for anything touching an external system, backend or provider. This change
introduces no backend and selects nothing: the extension point is `PostHook` (`core/hooks.py:70`), an
existing ABC with an existing registration path, and `A2UIPostHookFactory` follows the
`SandboxPreHookFactory` shape (`sandbox/hooks.py:134`) for enabled/disabled resolution only. There is
no `type` field and no second implementation to select, by design: an application wanting a different
payload format writes its own `PostHook` and attaches it, which is the BYO path and predates this
change. `core/util/payload.py` is a pydantic annotated type, not a component.

---

## Design

### `core/util/payload.py` — the JSON-safe payload type

New module. Holds one annotated type, used by `AgentReplyAny.content` and `DataMessage.content`.

```python
JSONPayload = Annotated[dict | list, BeforeValidator(_to_json_safe)]
```

**Why `core/util/`.** Both `core/model.py` and `core/event.py` need it, and `core/util/` is already
the home for small, stateless, framework-agnostic helpers shared across core (`factory.py`,
`error_util.py`, `pagination.py`, `key_value_cache.py`) — which is exactly this type's shape. It
keeps `core/`'s top level for the concepts.

One candidate home is ruled out rather than merely passed over: `core/model.py:8` imports
`core/event.py`, so defining the type in `model.py` and importing it from `event.py` would be an
import cycle. `event.py` itself would work — nothing imports back from it — but a payload rule is
not a stream event, and that is not where a reader would look.

**It cannot live in `a2ui/`.** The JSON-safe rule applies to *every* structured reply, labelled or
not; it is a property of `AgentReplyAny`, not of A2UI. Putting it in the capability package would
make `core/model.py` import from a capability, which the coupling rule forbids.

**Rules, numbered because the reasoning matters more than the code:**

1. **The validator is a single pydantic JSON round trip** — `json.loads(TypeAdapter(Any).dump_json(v))`
   — the same operation `from_output` already performs on its pydantic branch (`core/model.py:163`,
   `model_dump(mode="json")`). Applying it to the plain-dict branch is what makes the two converge.
   **Verified empirically** against the pinned pydantic: a `datetime` becomes ISO 8601, a `Decimal`
   a quoted string, a `UUID` a string, a `set` a list, `bytes` a string, an `int` key a string key,
   a top-level list passes through, and an arbitrary object raises `PydanticSerializationError`.
2. **Field-level (`BeforeValidator`), never a model validator.** A parent
   `model_validator(mode="after")` is bypassed by a subclass that fills `content` in its own
   after-validator — exactly the shape `AgentReplyPaused` takes in #696. Field validation runs for
   the subclass too. Decision 4 sends three constraints to #696 so that inheritance actually holds;
   they are that issue's to satisfy, not this one's.
3. **Values with a canonical JSON form coerce silently**: `datetime`, `date`, `Decimal`, `UUID`,
   `Enum`, `set`, `bytes`, and non-string mapping keys. Two surprises worth documenting rather than
   discovering, both verified:
   - **A `Decimal` becomes a quoted string, not a JSON number** (`Decimal("250.00")` → `"250.00"`),
     while a `float` stays a number. An application that puts a price in as a `Decimal` expecting a
     number on the wire gets a string.
   - **`bytes` coerce only when UTF-8 decodable.** A non-UTF-8 byte string raises
     (`invalid utf-8 sequence`) and therefore falls under rule 4, not rule 3.
4. **Values with no JSON form raise `ValidationError` at construction** — an arbitrary object, a
   file handle, a framework-native type. The validator catches the serializer's error and re-raises
   it as `ValueError`, which pydantic wraps into `ValidationError` naming the `content` field.
   (`PydanticSerializationError` *is* a `ValueError` subclass, so it would be wrapped anyway;
   re-raising is for the message, which otherwise names no field.)
5. **`NaN`, `inf` and `-inf` raise** — and this needs its own code, because pydantic does **not**
   raise: verified, `dump_json` renders all three as `null` silently. Decision 8: `null` is
   indistinguishable from an omitted field, so a client cannot tell a divide-by-zero from a value the
   agent chose not to send. Implemented by walking the payload for non-finite floats *before* the
   round trip and raising `ValueError` with the offending key path.
   - The walk is also where the **top-level shape** is checked: a scalar raises
     `ValueError("payload must be an object or array")` rather than reaching the round trip.
6. **Two bypasses no validator can close**, documented rather than defended against:
   `reply.model_copy(update={"content": ...})` and in-place mutation of an already-validated dict.
   The serialisation gates below use pydantic's encoder as defence in depth.

`_to_json_safe` is a module-level function — one of the justified exceptions in the house rules: it
is small, stateless, and belongs to no class (it is the validator body for an annotated type, which
cannot be a method).

### `core/model.py` — `AgentReplyAny`

```python
class AgentReplyAny(BaseModel):
    content: JSONPayload                       # was: dict
    media_type: str | None = None              # new
    prompt: str = ""
    type: Literal["other"] = "other"
```

- **`content` widens from `dict` (`core/model.py:143`) to `dict | list`.** A JSON array is a
  legitimate structured reply the type has always excluded, and A2UI forces it: on v0.9.1 a UI is a
  *sequence* of messages (Decision 10).
- **`from_output` (`core/model.py:151`) gains `list` in its second branch**, so a plain list is
  accepted the way a plain dict is. The `BaseModel` branch is untouched — a pydantic model still
  dumps to a dict.
- **`__str__` (`core/model.py:147`) is not edited.** It already calls `json.dumps(self.content,
  default=str)`, which serialises a list as readily as a dict. Its *output* changes for content that
  was never JSON-safe — see Behavioural changes.
- **`media_type` is never set by an adapter.** All six build replies through `from_output`, which
  takes no such parameter and gains none. The label is applied afterwards, by a post-hook.
- **`AgentReplyText` and `AgentReplyImage` do not gain the field.** A text reply has no content whose
  format needs naming.

### `core/event.py` — `DataMessage`

New member of the `StreamEvent` union (`core/event.py:131`), following the existing members' shape:

```python
class DataMessage(StreamEventBase):
    """A complete structured payload emitted inside the assistant's message."""

    type: Literal["data_message"] = "data_message"
    message_id: str
    content: JSONPayload
    media_type: str | None = None
```

- **`message_id`** ties it to the surrounding message, as `TextDelta` and `MessageEnd` do. It is
  emitted immediately before `MessageEnd`, and **only when the payload carries a media type** —
  matching the gate everywhere else.
- **Named for `a2a.helpers.new_data_message`**, the same concept on the other surface carrying this
  payload. `DataDelta` was rejected: it is not a fragment, and the name would invite streaming
  partial payloads, which Non-goals rules out.
- **`DataMessage` is exported from `core/__init__.py`** alongside the other members — that module
  already re-exports `MessageStart`, `TextDelta` and the rest (`core/__init__.py:15-25`), so omitting
  it would make this the one event type callers cannot import from `agentkernel.core`.
- **The module docstring's invariant must be amended in the same change**, not left contradicting the
  code. `core/event.py:16-17` currently reads "No field carries a framework-native object. Every
  field is a `str`, `int` or `bool`". The replacement names the enforced constraint rather than
  relaxing it: *a dict or list field carries a JSON-safe payload, guaranteed by the shared annotated
  type in `core/util/payload.py`*. The reason the invariant existed — `StreamChunk` crosses the queue
  transport in distributed topologies — is preserved.

### `a2ui/` — the capability

New top-level package, sibling to `sandbox/`. A capability, not an integration: it adds no surface.

```
a2ui/
├── __init__.py     # A2UIPostHook, A2UIPostHookFactory
└── hooks.py        # both classes
```

```python
class A2UIPostHook(PostHook):
    """Label a parsed reply from an agent the config declares to be an A2UI agent."""

    MEDIA_TYPE = "application/a2ui+json"   # Decision 11: adopted from the v1.0 RC,
                                           # which v0.9.1 does not define

    async def on_run(self, session, requests, agent, agent_reply):
        if not self._applies_to(agent):
            return agent_reply
        if not isinstance(agent_reply, AgentReplyText):
            return agent_reply
        try:
            payload = json.loads(agent_reply.response)
        except (ValueError, TypeError):
            return agent_reply
        if not isinstance(payload, (dict, list)):
            return agent_reply
        return AgentReplyAny(content=payload, prompt=agent_reply.prompt, media_type=self.MEDIA_TYPE)

    def name(self) -> str:
        return "A2UIPostHook"


class NoOpA2UIPostHook(PostHook):
    """Returned when the capability is disabled or fails to initialize."""


class A2UIPostHookFactory:
    """Returns the A2UI post-hook, or a no-op when the capability is disabled."""

    @staticmethod
    def get() -> PostHook: ...
```

**The detection rule, and its four deliberate exclusions.** The config block is a declaration; the
hook asks only whether the reply parsed. It does **not** read A2UI's `version`, does not look for
`createSurface` or any other message name, does not inspect component types, and does not check that
a list of messages is coherent. The framework's entire knowledge of A2UI is `MEDIA_TYPE`.

- `json.loads` of a scalar (`"4"`, `"true"`) succeeds and returns an `int`/`bool`, which
  `JSONPayload` would reject — hence the explicit `isinstance(payload, (dict, list))` guard, which
  returns the reply untouched rather than raising.
- `AgentReplyAny` is skipped, not labelled. A reply that is already structured means the application
  set `output_type`, whose schema is the application's; a hook labelling every `AgentReplyAny` would
  stamp prose as A2UI on every turn under the union route. Skipping is what keeps the config block
  and the `output_type` route from colliding.
- **Sequence coherence is not checkable by Agent Kernel and is not attempted.** Surfaces persist
  across turns; the spec states an agent "may skip [`createSurface`] if it knows the surface has
  already been created", and resending it is "an error … for a `surfaceId` that already exists". So
  `updateComponents` alone is correct A2UI. Whether a surface exists is client state.

**`_applies_to(agent)`** compares `agent.name` against `a2ui.agents`; `None` means all agents. Reading
config per call (rather than caching a resolved set on the instance) matches `SandboxPreHook` and
keeps one hook instance correct for every concurrent request — the hook holds **no mutable state**,
which is the concurrency contract: one instance serves all requests across all threads and event
loops.

**`A2UIPostHookFactory.get()`** copies `SandboxPreHookFactory.get()` (`sandbox/hooks.py:137-149`)
exactly: the real hook when `a2ui.enabled`, `NoOpA2UIPostHook` otherwise, and `NoOpA2UIPostHook` on
*any* initialization exception, logged via `logging.getLogger("ak.a2ui.hooks").exception(...)`. The
hook chain must never break the runtime.

### `core/chat_service.py` — the response builder

One change, in `ResponseBuilder.build_response` (`core/chat_service.py:303`). The current body
(`:317`) is a single expression; it becomes a branch:

```python
if isinstance(result, AgentReplyAny) and result.media_type:
    response_dict = {"result": result.content, "media_type": result.media_type}
else:
    response_dict = {"result": str(result) if isinstance(result, (AgentReplyText, AgentReplyImage, AgentReplyAny))
                     else "Non textual result received"}
```

- The `else` branch is the existing line, unmodified, so text replies, image replies, structured
  replies with no media type and the `"Non textual result received"` fallback are byte-for-byte what
  they are today.
- `__str__` is not edited; the builder stops calling it for labelled replies.
- This one function serves REST, WebSocket, async mode and conversation threads. No per-surface
  change is needed for any of them.

**`ResponseBuilder.stream_chunk` (`core/chat_service.py:338`)** changes `chunk.model_dump(exclude_none=True)`
(`:346`) to `chunk.model_dump(mode="json", exclude_none=True)`. Today's events are all
`str`/`int`/`bool`,
so this is byte-identical for them; without it a `DataMessage` reaches the bare `json.dumps` at
`:348` in python mode and can raise **mid-stream**, after the client has rendered part of the message.

### Serialisation gates

Four sites serialise a response body with a bare `json.dumps` and must use pydantic's encoder so a
value arriving through one of piece 1's bypasses produces the same bytes as everywhere else instead
of killing the message:

| Site | Current | Change |
|---|---|---|
| `pipeline/agent_runner.py:198` | `json.dumps(response_body)` | pydantic encoder |
| `pipeline/transport/sqs.py:52-67` | ECS twin | same |
| `deployment/aws/serverless/core/router/rest_lambda.py:288` | `json.dumps(res_body)` | same |
| `deployment/azure/akfunction.py:53` | `json.dumps(res_body)` | same |

`pipeline/request_handler.py:116` renders the 202 path through `JSONResponse`, which is
`json.dumps(..., allow_nan=False)`. Direct REST survives the same payload because FastAPI's
`jsonable_encoder` copes, so the two paths disagree — the per-surface divergence §2 argues against.
It changes to the same encoder.

### `core/util/driver/dynamodb.py` — float ↔ Decimal

`DynamoDBDriver.put` (`:84`) does no float conversion, so boto3 raises `Float types are not supported`
inside the output consumer, burning the retry budget. Any payload carrying a price, a score or a
coordinate trips it. Piece 1's JSON-safe rule does **not** fix this — JSON-safe means the float stays
a float.

Two private static methods on the driver, so the conversion lives in the class that owns the
database semantics:

- `_to_dynamo(value)` — recursively rewrites `float` → `Decimal(str(value))` in `put`.
- `_from_dynamo(value)` — the inverse in `get`, `query` and any scan path: `Decimal` → `int` when
  integral, else `float`.

**The read side is half the fix, not an afterthought.** Without it the failure moves one hop: the
pipeline `RestHandler` hands `record["body"]` straight to FastAPI (`pipeline/request_handler.py:117`),
whose encoder copes with `Decimal`, but the Lambda poll path does `json.dumps` on the polled record
(`rest_lambda.py:288`) and raises `TypeError`. **The rule: no consumer ever sees a `Decimal`.**

### `api/mcp/akmcp.py` — MCP

`MCP.Executor.execute` (`:39`) currently calls `service.run(prompt=prompt)`, which stringifies one
layer lower in `AgentService.run` (`core/service.py:156`). It switches to `run_multi` and branches:

```python
reply = await service.run_multi([AgentRequestText(prompt=prompt)])
await ctx.debug(f"Agent response '{reply}'")
if isinstance(reply, AgentReplyAny) and reply.media_type:
    return ToolResult(structured_content=reply.content, meta={"media_type": reply.media_type})
return str(reply)
```

- The `-> Any` annotation and the `ctx` logging are untouched. Verified against the pinned fastmcp
  (3.4.7): a dict return annotated `-> Any` already produces `structuredContent`, and a `ToolResult`
  carrying `meta` round-trips to a client intact.
- **Any reply without a media type** — text, image, or structured-but-unlabelled — still produces
  exactly the string it does today (`:45` returns `response`, which `str()` already yielded).
- **The key is `media_type` here and `mimeType` on A2A — deliberately, not an oversight.** A2UI
  publishes an A2A binding that names `mimeType`, so A2A uses A2A's word. MCP has no such binding, so
  `_meta` carries Agent Kernel's own name, matching the reply field and the REST response key.
- `_meta` is MCP's own slot for implementation metadata. The rejected alternative was wrapping the
  payload (`{"media_type": …, "content": …}`), which changes the shape the client receives.

### `api/a2a/a2a.py` — A2A

**A2A does not import today**, so this piece starts by fixing that. `ak-py/uv.lock` pins
`a2a-sdk 1.1.2`, and in that venv `import agentkernel.api.a2a.a2a` raises
`ImportError: cannot import name 'new_agent_text_message' from 'a2a.utils'`. Nothing is red because
no test imports the module.

**The fix here is a cap, not a port.** `ak-py/pyproject.toml:168` becomes
`a2a-sdk[http-server]>=0.3.6,<0.4` and `ak-py/uv.lock` is regenerated — backwards, 1.1.2 → 0.3.x,
which is safe because nothing uses 1.1.2: the module does not import against it, so no code path
exercises it. The 1.x port is a separate issue (Decision 6), and it is a bigger job than the design
first assumed: **1.x replaced the pydantic types with protobuf.** `new_data_message` returns an
`a2a_pb2.Message` with no `model_dump`, so porting is an object-model migration rather than three
renamed imports.

On the capped SDK:

- `_execute_agent` (`:60`) calls `run_multi([AgentRequestText(prompt=...)])` instead of `run(prompt)`,
  so the executor receives an `AgentReply` rather than a string. Its return annotation tightens from
  `Any` to `AgentReply`.
- `execute` (`:42`) branches **on the media type, not the reply type** at `:49`. **Verified against
  a real 0.3.6 install** — this exact call produces `kind: data` with the payload intact and the
  label in `metadata`:

  ```python
  new_agent_parts_message(
      [Part(root=DataPart(data=reply.content, metadata={"mimeType": reply.media_type}))],
      context_id, task_id)
  ```

  Everything else — including a structured reply with no label — keeps `new_agent_text_message`, and
  the error path (`:54`) stays text.
- **The metadata key is `mimeType`.** A2UI's A2A binding (its v0.8 extension spec) names that key
  inside `DataPart.metadata`, and A2A's `DataPart` has no `mimeType` field of its own — `data`,
  `kind`, `metadata` only — so `metadata` is both correct and the only option. Agent Kernel's own
  `media_type` naming stays on its own surfaces; on A2A it uses A2A's word.
- **`A2A._build` (`api/a2a/a2a.py:76`) declares the extension** on each covered agent's card:

  ```python
  card.capabilities.extensions = [*(card.capabilities.extensions or []),
                                  AgentExtension(uri=A2UI_EXTENSION_URI, required=False)]
  ```

  `AgentCapabilities.extensions` and `AgentExtension(uri, description, params, required)` both exist
  on the capped SDK — verified. This is the **only** place a surface learns A2UI exists (Decision
  12): `a2ui/` exposes the URI constant and an `is_enabled_for(agent_name)` predicate, and
  `api/a2a/a2a.py` builds the `AgentExtension` itself, so `core/` stays free of A2UI and `a2ui/`
  stays free of the a2a SDK.
- **A2A gets its first test file**, `tests/test_a2a.py`. It has none today, which is the only reason
  the broken import never went red.
- The agent card already advertises `default_output_modes: ["json"]` (`core/builder.py:44`) while the
  executor only ever sends text. This makes an existing claim true rather than adding a new one.
- **The label's position changes at the port.** On 0.3.x it rides in
  `DataPart.metadata["mimeType"]`, which is what A2UI's binding specifies; on 1.x it is a
  first-class `media_type` field on the part. That
  is a breaking change for an A2A client reading the label — of which there are none today, because
  A2A has never sent a data part. The port issue owns the migration note.

### `integration/agui/mapping.py` — AG-UI

One `case "data_message"` above the `case _` fallback (`:64`), producing AG-UI's custom event with
`media_type` as the name and `content` as the value. Unmapped types already return `None`, so an
AG-UI client on an older mapper degrades rather than breaks.

### `integration/thread/recorder.py` — thread recording

`ThreadRecorder.post_run` (`:59`) stores `str(result)` into `ThreadMessage.content` (`:66`). Through
the queue, `AgentRunner` passes the already-built response body's `result` value
(`pipeline/agent_runner.py:61`), which for a labelled reply is now a **dict**, and `str()` on a dict
yields a Python repr — single quotes, `None`, `True`. The direct thread handler stores proper JSON
for the same reply. So the same agent, in the same thread store, would be recorded one way in
single-process mode and another through the queue, permanently.

**The two call sites pass different types, which is what makes this easy to get wrong.** Verified:

| Caller | `result` is | `str(result)` gives |
|---|---|---|
| `integration/thread/thread_chat.py:136` (direct) | an `AgentReply` **object** | `json.dumps(content)` — already correct |
| `integration/thread/thread_chat.py:178` (direct, streamed) | a `str` of joined deltas | itself — correct |
| `pipeline/agent_runner.py:151` (queue) | the response body's `result` **value** — a `dict` once labelled | a Python **repr** — the defect |

So the fix cannot be "always `json.dumps`": that would raise `TypeError` on the direct path's model
object. `post_run` normalises by type instead:

```python
if isinstance(result, str):
    content = result
elif isinstance(result, (dict, list)):
    content = json.dumps(result)          # the queue path's labelled reply
else:
    content = str(result)                 # an AgentReply — its __str__ is already json.dumps
```

`ThreadMessage.content` stays `str` (`integration/thread/model.py:33`) — **labelling stored history
is a Non-goal**; this fixes the encoding only.

### Consumer changes

| Consumer | Change |
|---|---|
| Six framework adapters | **None.** They call `from_output` with no media type and are unaffected. Verified: no adapter sets or reads `media_type`. |
| `core/service.py:144` `AgentService.run` | **None.** Still returns `str`. A2A and MCP move to `run_multi`; the CLI keeps `run`. |
| `pipeline/ws/base.py` | **None.** `send(..., message: dict)` passes the response dict through as a JSON frame, so WebSocket gets the object form free. |
| Redis / Valkey response stores | **None, verified.** They re-serialise a body that is already JSON-native. |
| `pipeline/response_handler.py:192` | **None — deliberately.** The messaging integrations receive a Python repr for a labelled reply; they are text surfaces with no A2UI renderer, and pointing a labelled agent at one is the application's choice. Non-goal, recorded with the consequence spelled out. |
| Existing test fixtures and example clients | **None.** All unlabelled. |

### Config changes

One new block. **`_A2UIConfig`**, placed beside `_SandboxConfig` (`core/config.py:786`) and registered
on `AKConfig` beside `sandbox` (`core/config.py:919`):

```python
class _A2UIConfig(BaseModel):
    enabled: bool = Field(
        default=False,
        description="Enable the A2UI capability; when False no hook runs and no reply is labelled",
    )
    agents: Optional[list[str]] = Field(
        default=None,
        description="Agent names whose JSON replies are labelled as A2UI; omitted = all agents",
    )
```

```python
a2ui: _A2UIConfig = Field(description="A2UI capability configurations", default_factory=_A2UIConfig)
```

**Config reuse audited.** Every `class _` in `core/config.py` was enumerated (68 models). No existing
model expresses `enabled + agents` and nothing else: `_SandboxConfig` carries eight further fields,
`_A2AConfig`/`_MCPConfig` are surface blocks with URLs and transport settings. There is nothing to
reuse whole or subclass for defaults only.

**Why `enabled` is justified rather than derived.** The house rule prefers already-configured
components to enable a feature implicitly. Nothing here can stand in: this capability owns no store,
no provider and no surface, so there is no configured component whose presence implies it. It also
changes what a client receives, which the rule requires a deliberate flag for (`sandbox.enabled`,
`trace.enabled`, `guardrail.enabled` are the precedents). **Read by** `A2UIPostHookFactory.get()`.

**Why `agents` is `Optional[list[str]] = None`, not `List[str] = ["*"]`.** Two conventions exist in
the file and the asymmetry is real: surface blocks use the wildcard (`_A2AConfig:141`,
`_MCPConfig:149`), capability blocks use optional-none (`_SandboxConfig:790`, `_AGUIConfig:877`).
A2UI is a capability, so it follows the capability convention. **Read by**
`A2UIPostHook._applies_to`.

**Compatibility.** Both fields have defaults, so existing `config.yaml` files and `AK_*` env vars
stay valid with the capability inert. The block is reachable as `AK_A2UI__ENABLED` and
`AK_A2UI__AGENTS` through the standard `AK_`/`__` nesting.

**No `type` selector and no extra.** There is one implementation and no optional SDK; adding either
would be the "first backend as the only backend" antipattern in reverse — machinery with nothing to
select.

### Behavioural changes

Numbered, exhaustive. Every one is intentional.

1. **A labelled `AgentReplyAny` produces `{"result": <object>, "media_type": <str>}` from
   `build_response`** instead of `{"result": "<json string>"}`. Gated: unreachable without a
   `media_type`, which no adapter sets. *Justification:* the change's purpose (Decision 3).
2. **`result` becomes `str | dict | list`.** A client must read `media_type` to know which it has.
   *Justification:* Decision 3 plus Decision 10 — the third shape is A2UI v0.9.1's message sequence.
3. **`str(AgentReplyAny(...))` changes output for content that was never JSON-safe.** A `datetime`
   becomes ISO 8601 rather than `str()`'s space-separated form; a `Decimal` becomes a JSON number
   rather than a quoted string; a `set` becomes a list. *Justification:* the four encoders converge
   on one form (Piece 1). **This is the only behavioural change that is not gated on a media type**,
   and the only changelog line the design requires.
4. **`AgentReplyAny(content=...)` now raises `ValidationError` for an unserialisable object**, where
   it previously accepted it and `default=str` shipped `"<Row object at 0x…>"` to a client as data.
   *Justification:* raising at construction beats shipping a repr as data.
5. **`AgentReplyAny(content=...)` raises for `NaN` / `inf` / `-inf`.** *Justification:* Decision 8.
6. **`AgentReplyAny.content` accepts a top-level list.** Widening only; no previously valid input is
   rejected. *Justification:* Decision 10.
7. **The DynamoDB response store converts floats to `Decimal` on write and back on read.** A payload
   carrying a float previously failed the write outright. Round-tripped values are `float`/`int`, not
   `Decimal`, on every read path. *Justification:* the feature ships broken otherwise.
8. **Thread recording through the queue stores JSON rather than a Python repr for a labelled reply.**
   Unreachable today, since `result` is never a dict at that point. *Justification:* the two thread
   paths must not diverge permanently.
9. **MCP returns a `ToolResult` with `structuredContent` and `_meta` for a labelled reply.** Gated.
   *Justification:* Piece 4.
10. **A2A sends a data part for a labelled reply.** Gated. *Justification:* Piece 4.
11. **`a2a-sdk` is capped to `>=0.3.6,<0.4`.** A2A becomes importable again; the lock moves backwards
    from 1.1.2, which nothing was using. *Justification:* a working A2A inside this issue, and a
    tested one for the port issue to migrate.
12. **A streamed run can emit a `DataMessage` before `MessageEnd`.** Only when an application hook
    produces one; nothing in the framework emits it. *Justification:* Piece 3.
13. **`stream_chunk` serialises in JSON mode.** Byte-identical for every event type that exists
    today. *Justification:* prevents a mid-stream raise.

**Non-changes — fixed on purpose:**

- `__str__`'s *code*, the `AgentReply` union, and every framework adapter.
- `AgentService.run`'s signature and return type (`str`).
- `ThreadMessage.content`'s type (`str`) and the thread read routes.
- `pipeline/response_handler.py`'s messaging path.
- The response dict for any reply without a `media_type` — byte for byte, including the
  deferred-schedule 202 acknowledgement (`core/chat_service.py:496` builds an `AgentReplyAny` with no
  media type).
- Every `result` example in the published docs (six files) and every `["result"]` read in the example
  test suites (seven, across four files) — all text or unlabelled.

---

## Error handling

| Failure | Surfaces as |
|---|---|
| Unserialisable value in `content` | `ValidationError` at construction, naming the field. Raised in the application's own code, not down the pipeline. |
| `NaN`/`inf` in `content` | `ValueError` from the validator with the offending key path, wrapped by pydantic into `ValidationError`. |
| A value reaching a serialisation gate through a bypass | Encoded by pydantic's encoder rather than raising `TypeError` and losing the message to retry exhaustion. |
| `a2ui` block absent or `enabled: false` | `A2UIPostHookFactory.get()` returns `NoOpA2UIPostHook`. No error, no log noise. |
| `A2UIPostHookFactory.get()` raises | Logged via `logging.getLogger("ak.a2ui.hooks").exception(...)`; returns `NoOpA2UIPostHook`. The hook chain never breaks the runtime. |
| Reply body is not JSON | Returned untouched and unlabelled — the normal prose case, not an error. Not logged: it is most turns. |
| Reply body parses to a scalar | Returned untouched. Guarded explicitly so `JSONPayload` never sees it. |
| Reply parses but is not valid A2UI | Labelled and forwarded. Agent Kernel does not validate; the renderer rejects it, which is the correct and visible outcome. |
| `DataMessage` with an unsafe value | Cannot occur — `JSONPayload` rejects at construction, before the stream. |
| DynamoDB write of a float | Converted to `Decimal`; no longer raises. |
| MCP host ignores `_meta` | The client receives the payload without knowing its format. Accepted (Decision 9) — a host integration problem, not a reason to invent a wrapper. |
| A2A on an uncapped install | The cap makes this unreachable from `pyproject.toml`. An environment that forces 1.x still fails to import — the port issue's to fix. |

---

## Testing

Run with `cd ak-py && uv run pytest`.

### New files

**`tests/test_payload.py`** — the `JSONPayload` type directly.

- **Convergence, the whole rule in one assertion:** a pydantic model with `datetime`/`Decimal`/`UUID`
  fields through `from_output`, and a plain dict of the same values through
  `AgentReplyAny(content=...)`, produce **equal** `content`.
- Parameterised coercion: `datetime`, `date`, `Decimal`, `UUID`, `Enum`, `set`, `bytes`, non-string
  keys.
- Raises: an arbitrary object; `NaN`; `inf`; `-inf`.
- A top-level list validates; a scalar does not.
- **The bypasses, pinned as tested behaviour:** `model_copy(update={"content": ...})` does *not*
  normalise, and neither does in-place mutation. Pin them so nobody builds on a guarantee that is
  not there.

**`tests/test_a2ui_hook.py`** — the capability, with `AKConfig.get` monkeypatched per the
`test_sessions_redis.py` fake-config pattern.

- A text reply whose body parses as an object is labelled `application/a2ui+json`; as a **list**,
  likewise.
- A greeting is returned untouched and unlabelled — the same object identity.
- An `AgentReplyAny` is returned untouched: the guard that stops the config block colliding with an
  `output_type` agent.
- An `AgentReplyImage` is returned untouched.
- A body parsing to a scalar (`"4"`) is returned untouched.
- `agents: ["other"]` excludes the agent under test; `agents: None` includes it.
- `enabled: false` and an absent block both yield `NoOpA2UIPostHook`.
- A factory whose config read raises degrades to the no-op rather than failing the run.
- **End-to-end, once:** config on, an agent returning an A2UI document, `result` arrives as an
  object with `media_type` set — with **no application post-hook anywhere in the test**.

**`tests/test_cross_surface_parity.py`** — one labelled structured reply asserted to arrive with the
same content and the same label on REST, WebSocket, MCP and AG-UI (A2A's leg lands with the A2A
branch, after the port). Nothing like it exists today; it is what makes §3's claim checkable and what
catches a future surface regressing to an early encode. **The fixture must carry a `datetime` and a
`Decimal`** — parity on a payload that was never at risk proves nothing.

### Changed files

| File | Change |
|---|---|
| `tests/test_model.py` | `media_type` defaults to `None` and round-trips; `content` accepts a list; `__str__` parameterised — byte-identical for JSON-safe content, and the pinned new output for `datetime`/`Decimal`/`set`, and **raises** for `NaN`. |
| `tests/test_chat_service_core.py` | `build_response` matrix: labelled → dict + `media_type`; unlabelled structured, text, image and the non-reply fallback → unchanged strings. Plus the regression test for the gap Copilot found: build a response for a reply whose content carried a `datetime`, then assert `json.dumps(response_body)` succeeds — reproducing `agent_runner._send_to_output`'s exact call. |
| `tests/test_api_http.py:412` | `TestResponseBuilderStructuredResult.test_structured_result_serialized_as_json_string` pins `response["result"] == json.dumps(content)` today. It becomes a matrix — **that exact assertion must keep passing** for the unlabelled case, with a labelled sibling asserting the dict. This is the back-compat guarantee, tested directly. |
| `tests/test_chat_service_streaming.py` | A `DataMessage` chunk serialises; `stream_chunk` in JSON mode is byte-identical for existing event types. |
| `tests/test_stream_events.py` | `DataMessage` round-trips through the discriminated union on `type`. |
| `tests/test_agui_mapping.py` | `data_message` → AG-UI custom event; an unknown type still returns `None`. |
| `tests/test_pipeline_agent_runner.py` | A labelled reply reaches the output queue (the bare `json.dumps` no longer raises), and thread recording stores valid JSON, not a Python repr. |
| `tests/test_thread_runner.py` | The queue path and the direct path record the **same bytes** for the same labelled reply. |
| `tests/test_sessions_dynamodb.py` / `tests/test_shared_drivers.py` | A payload carrying a float is stored without raising **and reads back as a `float`, not a `Decimal`** — asserted by a `json.dumps` on the polled record, which is what `rest_lambda.py:288` does and what would fail if only the write side were fixed. |
| `tests/test_api_mcp.py` | A labelled reply produces `structuredContent` plus `_meta`; an unlabelled one produces today's string. |
| `tests/test_config.py` | The `a2ui` block loads, defaults to disabled, and accepts `AK_A2UI__*`. |

**Riskiest consumer.** `pipeline/agent_runner.py` changes shape the most for a labelled reply — it
feeds the output queue *and* thread recording from the same value. `tests/test_pipeline_agent_runner.py`
exists and covers it; both new assertions go there rather than into a new file.

### Example

One runnable example under `examples/`: an agent with its own catalog in its instructions, the `a2ui`
block turned on, and the payload arriving over plain REST with no UI framework involved. Its
`app_test.py` asserts `media_type` is present and `result` is an object — the only example test in the
repo that reads a non-string `result`.
