# #706: structured replies carry their format, end to end — Implementation Spec

`AgentReplyAny` gains a `media_type` field and a JSON-safe `content`; every non-streaming exit point
emits `content` as an object when that field is set and the string it emits today when it is not; a
new `DataMessage` stream event carries the same pair mid-stream; and one small `a2ui` capability sets
the label from two config keys. Requirements come from [`design.md`](design.md) — this document is
how they are built, not whether. Where the two disagree, `design.md` is authoritative and this file
is wrong.

Code facts verified against `develop` at `97fa8d91`, the current merge base — re-pinned from
`80936df9`, which predated the human-in-the-loop merge (#606). **Line citations resolve against this
branch**, not against that merge base, so a reviewer reading the PR can follow them; the re-pin
moved them by 20 to 120 lines in `core/model.py`, `core/chat_service.py`, `core/event.py` and
`core/config.py`. Paths are relative to `ak-py/src/agentkernel/` unless stated. Protocol facts verified against
[a2ui.org](https://a2ui.org/) (September 2026): **v0.9.1 is Current, v1.0 is a release candidate**.

**Pluggability note, stated so a reviewer can confirm rather than flag it.** The house rule is ABC +
factory + dotted-path BYO for anything touching an external system, backend or provider. This change
introduces no backend and selects nothing: the extension point is `PostHook` (`core/hooks.py:70`), an
existing ABC with an existing registration path, and `A2UIPostHookFactory` follows the
`SandboxPreHookFactory` shape (`sandbox/hooks.py:134`) for enabled/disabled resolution only. There is
no `type` field and no second implementation to select, by design: an application wanting a different
payload format writes its own `PostHook` and attaches it, which is the BYO path and predates this
change. **Every component this change introduces is a class**, per the house rules: `PayloadCodec`
(`core/util/payload.py`), `DynamoDecimalCodec` (beside the DynamoDB driver), `DataMessage`
(`core/event.py`), `A2UIPostHook` / `NoOpA2UIPostHook` / `A2UIPostHookFactory` (`a2ui/hook.py`) and
`_A2UIConfig` (`core/config.py`). **One module-level name survives** — `JSONPayload`, a pydantic
annotated type, which cannot be anything else and is a type alias rather than a component. Every
other change edits a method on a class that already exists.

---

## Design

### `core/util/payload.py` — `PayloadCodec`

New module. **One class**, not a pair of module-level functions, because both halves answer the same
question — *what bytes does this value become* — and splitting them is how the four encoders diverged
in the first place.

```python
class PayloadCodec:
    """Normalises a payload to plain JSON types, and encodes any response body to JSON."""

    _adapter: TypeAdapter = TypeAdapter(Any)

    @classmethod
    def normalise(cls, value: Any) -> dict | list: ...      # the validator body
    @classmethod
    def encode(cls, body: Any) -> str: ...                  # lenient; the queue boundary
    @classmethod
    def as_text(cls, value: Any) -> Any: ...                # the JSONText validator body
    @classmethod
    def _require_finite(cls, value: Any, path: str = "content") -> None: ...  # private


JSONPayload = Annotated[dict | list, BeforeValidator(PayloadCodec.normalise)]
JSONText = Annotated[str, BeforeValidator(PayloadCodec.as_text)]
```

`JSONPayload` and `JSONText` are module-level names because a pydantic annotated type cannot be
anything else; they are type aliases, not components. `PayloadCodec` holds no instance state and is used as a namespace with
behaviour, so every method is a `@classmethod` — the house rules' stated form for a class needing no
instance.

**`normalise` — used by `AgentReplyAny.content` and `DataMessage.content`:**

1. **Rejects a non-object top level** before anything else: `json.loads("4")` succeeds and yields an
   `int`, which is not a payload.
2. **`_require_finite` walks for non-finite floats and raises**, naming the key path
   (`content['stats']['avg'] is nan`). This needs its own code: pydantic renders `NaN` and the
   infinities as `null` **silently** — verified — and `null` is indistinguishable from an omitted
   field, so a client could not tell a divide-by-zero from a deliberate gap (Decision 8).
3. **Round-trips**: `json.loads(TypeAdapter(Any).dump_json(value))`. The same operation `from_output`
   already performs on its pydantic branch (`core/model.py:265`), applied to the plain-dict branch so
   the two converge. Verified: `datetime` → ISO 8601, `Decimal` → quoted string, `UUID`/`bytes` →
   string, `set` → list, `int` key → string key, top-level list passes.
4. **Re-raises a serializer failure as `ValueError`**, which pydantic wraps into a `ValidationError`
   naming the `content` field. (`PydanticSerializationError` is itself a `ValueError` subclass, so it
   would be wrapped anyway; re-raising is for the message, which otherwise names no field.)

**`normalise` runs twice for a labelled reply**, once on the field and once in
`ResponseBuilder.build_response`. Not redundant: the second run is the only thing that sees a
payload replaced by `model_copy` or mutated in place after validation (§ *Serialisation gates*).

**`encode` — the one lenient method, and only because of where it runs.** The same round trip,
then `json.dumps`, with a non-finite float rendered as `null` rather than raised on. That is right
at a queue boundary and nowhere else: a raise there loses the message to retry exhaustion and tells
the caller only `"Failed to process message after N retries"`. A reply being assembled in-process
has no such problem, which is why `ResponseBuilder` re-runs `normalise` instead of reaching for
this (§ *Serialisation gates*).

**`as_text` — used by `QueueMessage.body`:** `encode` for a dict or a list, pass-through for
anything else, so a `str` body keeps its exact bytes and a scalar still fails the field's own `str`
validation. Deliberately thin. It exists so the encoding rule can live on a *field* rather than in
the memory of whoever writes the next transport, which is the same reason `normalise` lives on
`content` rather than at each reply's construction site.

Two surprises worth documenting rather than discovering, both verified: a `Decimal` becomes a
**quoted string** while a `float` stays a number, and `bytes` coerce **only when UTF-8 decodable** —
a non-UTF-8 byte string raises, so it falls under rule 4 rather than rule 3.

**`encode` — used by every serialisation gate.** This is the half that stops the fix being copied
four times. Each gate below calls `PayloadCodec.encode(body)` instead of `json.dumps(body)`, so a
value that got in through one of normalisation's two bypasses produces the same bytes everywhere
rather than a `TypeError` that loses the message to retry exhaustion.

**Two bypasses no validator can close**, documented rather than defended against:
`reply.model_copy(update={"content": ...})` and in-place mutation of an already-validated dict.
`encode` is the defence in depth.

**Why `core/util/`.** Both `core/model.py` and `core/event.py` need it, and `core/util/` is already
the home for small, stateless, framework-agnostic helpers shared across core (`factory.py`,
`error_util.py`, `pagination.py`, `key_value_cache.py`). It keeps `core/`'s top level for the
concepts.

One candidate home is ruled out rather than merely passed over: `core/model.py:8` imports
`core/event.py`, so defining the type in `model.py` and importing it from `event.py` would be an
import cycle. `event.py` itself would work — nothing imports back from it — but a payload rule is
not a stream event, and that is not where a reader would look.

**It cannot live in `a2ui/`.** The JSON-safe rule applies to *every* structured reply, labelled or
not; it is a property of `AgentReplyAny`, not of A2UI. Putting it in the capability package would
make `core/model.py` import from a capability, which the coupling rule forbids.

### `core/model.py` — `AgentReplyAny`

```python
class AgentReplyAny(BaseModel):
    content: JSONPayload                       # was: dict
    media_type: str | None = None              # new
    prompt: str = ""
    type: Literal["other"] = "other"
```

- **`content` widens from `dict` (`core/model.py:238`) to `dict | list`.** A JSON array is a
  legitimate structured reply the type has always excluded, and A2UI forces it: on v0.9.1 a UI is a
  *sequence* of messages (Decision 10).
- **`from_output` (`core/model.py:247`) is *not* widened** — a bare list stays unstructured there,
  even though `content` accepts one. An earlier draft of this spec widened it; implementing that
  showed it changes `result` for an agent that never opted in: a list-returning framework produced
  `AgentReplyText(str(["a", "b"]))` → `"['a', 'b']"`, and promoting it to `AgentReplyAny` makes that
  `'["a", "b"]'`. Ungated, so it contradicts Decision 3's guarantee. A caller that means to send an
  array builds the reply itself, which is what piece 5's hook does — the only thing the widening was
  needed for.
- **`__str__` (`core/model.py:243`) is not edited.** It already calls `json.dumps(self.content,
  default=str)`, which serialises a list as readily as a dict. Its *output* changes for content that
  was never JSON-safe — see Behavioural changes.
- **`media_type` is never set by an adapter.** All six build replies through `from_output`, which
  takes no such parameter and gains none. The label is applied afterwards, by a post-hook.
- **`AgentReplyText` and `AgentReplyImage` do not gain the field.** A text reply has no content whose
  format needs naming.

### `core/event.py` — `DataMessage`

New member of the `StreamEvent` union (`core/event.py:220`), following the existing members' shape:

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
  already re-exports `MessageStart`, `TextDelta` and the rest (`core/__init__.py:16-32`), so omitting
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
└── hook.py         # both classes
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
*any* initialization exception, logged via `logging.getLogger("ak.a2ui.hook").exception(...)`. The
hook chain must never break the runtime.

### `core/chat_service.py` — the response builder

One change, in `ResponseBuilder.build_response` (`core/chat_service.py:326`). The current body
(`:354-355`) is a single expression; it becomes a branch:

```python
if isinstance(result, AgentReplyAny) and result.media_type:
    response_dict = {"result": result.content, "media_type": result.media_type}
else:
    response_dict = {
        "result": str(result)
        if isinstance(result, (AgentReplyText, AgentReplyImage, AgentReplyAny))
        else "Non textual result received"
    }
```

- The `else` branch is the existing line, unmodified, so text replies, image replies, structured
  replies with no media type and the `"Non textual result received"` fallback are byte-for-byte what
  they are today.
- `__str__` is not edited; the builder stops calling it for labelled replies.
- This one function serves REST, WebSocket, async mode and conversation threads. No per-surface
  change is needed for any of them.

**`ResponseBuilder.stream_chunk` (`core/chat_service.py:400`)** changes `chunk.model_dump(exclude_none=True)`
(`:397`) to `chunk.model_dump(mode="json", exclude_none=True)`. Today's events are all
`str`/`int`/`bool`,
so this is byte-identical for them; without it a `DataMessage` reaches the bare `json.dumps` at
`:348` in python mode and can raise **mid-stream**, after the client has rendered part of the message.

### Serialisation gates

Several sites serialise a response body with a bare `json.dumps`. A value arriving through one of
`normalise`'s two bypasses raises `TypeError` there, the message is lost to retry exhaustion, and the
caller is told `"Failed to process message after N retries"` — naming neither cause nor fix.

**The fix is not a call at each site.** That was the first shape of this work: `PayloadCodec.encode`
wherever a body becomes text. It is a rule somebody has to remember, and the person adding the next
deployment target or queue transport has no way to learn it exists. Worse, it misdirects: a reader
who finds `encode` at a seam concludes the seam owns the rule. Both deployment adapters disprove
that on sight — each writes its own error body with a bare `json.dumps` two lines away.

So the rule goes where it cannot be skipped, in two forms, and the call sites mostly disappear.

**First: the producer guarantees it.** Every value in a response body is already a `str` or a
`model_dump(mode="json")` except one — the object form, which is the point of this change and the
only way a payload reaches a client untouched. So that branch alone re-normalises:

```python
elif isinstance(result, AgentReplyAny) and result.media_type:
    response_dict = {"result": PayloadCodec.normalise(result.content), "media_type": result.media_type}
```

which buys the invariant everything else rests on: **anything `ResponseBuilder.build_response`
returns survives a bare `json.dumps`.** The obvious code is the correct code, for surfaces that do
not exist yet. An unlabelled reply pays nothing, since `result` is a string there.

**`normalise`, not a lenient variant.** It raises on a `NaN`, where the lenient path renders
`null` — indistinguishable from a field the agent chose to omit, which is the whole reason
Decision 8 refuses it at construction. Refusing it here too costs a caller nothing it wants: the
error names the key path and is reported, where `null` ships wrong data quietly. The leniency
argument belongs to the queue boundary, where a raise loses the message instead of reporting
anything; a reply assembled in-process is not in that position.

**Second: where the boundary has a model, the field carries it.** `QueueMessage.body` takes a
`JSONText` annotation — the same trick `JSONPayload` plays on `content` — and encodes a dict or list
on validation, passing a `str` through byte for byte. Not cosmetic: SQS, Kafka and NATS all call
`.encode()` on the body and raise `AttributeError` on a dict, while the in-memory transport stores
the envelope as an object and never notices. Left to each sender, the rule would hold in
development and break in production.

**What remains is one gate.** `serialize_message_body` (`pipeline/transport/sqs.py:52-67`) keeps it,
because it also serves `SQSHandler`'s direct callers, whose bodies passed through neither a
`QueueMessage` nor the response builder. Everywhere else writes a plain `json.dumps`:

| Site | Why no gate |
|---|---|
| `deployment/aws/serverless/core/router/rest_lambda.py:288` | Body is `build_response`'s, already normalised |
| `deployment/azure/akfunction.py:53` | Same |
| `deployment/aws/core/websocket_service.py:167` | Direct routes push `build_response`'s body; every other caller holds one it just read back with `json.loads` |
| `pipeline/request_handler.py:122` | Record came off the wire as text |

`pipeline/request_handler.py:122` still builds a plain `Response` rather than a `JSONResponse`, for
a reason unrelated to payloads. `JSONResponse` encodes with `allow_nan=False`, and a `NaN` reaches a
stored record the ordinary way — stdlib `json.dumps` writes the token `NaN` onto the queue and
`json.loads` reads it back as a float — so the 202 path would 500 where FastAPI's own return path
writes it through. That is the per-surface divergence §2 argues against, and it is pinned by a test.

**The WebSocket push is the one found late.** Only the *direct* (non-queue) routes reach it with a
freshly built body: ECS `_process_chat_direct` and `ws_lambda._process_chat` call `ChatService`
in-process and broadcast the reply. That body is `build_response`'s, so it is safe for the same
reason the rest are. `pipeline/ws/push.py` was checked and needs nothing: the pipeline's WebSocket
gateway always enqueues (`ws/handler.py:231`), so nothing reaches it without crossing the wire.

### `core/util/driver/dynamodb.py` — float ↔ Decimal

`DynamoDBDriver.put` (`:137`) does no float conversion, so boto3 raises `Float types are not supported`
inside the output consumer, burning the retry budget. Any payload carrying a price, a score or a
coordinate trips it. Piece 1's JSON-safe rule does **not** fix this — JSON-safe means the float stays
a float.

**`DynamoDecimalCodec`**, a class beside `DynamoDBDriver` in the same module, mirroring
`PayloadCodec`'s shape — both are codecs, and a reader who has met one should recognise the other:

```python
class DynamoDecimalCodec:
    """Converts between JSON numbers and DynamoDB's Decimal-only numeric type."""

    @classmethod
    def to_dynamo(cls, value: Any) -> Any: ...    # float -> Decimal(str(value)), recursively
    @classmethod
    def from_dynamo(cls, value: Any) -> Any: ...  # Decimal -> int when integral, else float
```

`DynamoDBDriver.put` calls `to_dynamo`; `get`, `query` and any scan path call `from_dynamo`. A
separate class rather than two driver methods because the conversion is a self-contained rule with
its own tests, and the driver should not grow a second responsibility — but it stays in the driver's
module, because it is DynamoDB's semantics and nothing else needs it.

**The read side is half the fix, not an afterthought.** Without it the failure moves one hop: the
pipeline `RestHandler` hands `record["body"]` straight to FastAPI (`pipeline/request_handler.py:117`),
whose encoder copes with `Decimal`, but the Lambda poll path does `json.dumps` on the polled record
(`rest_lambda.py:288`) and raises `TypeError`. **The rule: no consumer ever sees a `Decimal`.**

### `api/mcp/akmcp.py` — MCP

`MCP.Executor.execute` (`:41`) currently calls `service.run(prompt=prompt)`, which stringifies one
layer lower in `AgentService.run` (`core/service.py:156`). It switches to `run_multi` and branches:

```python
reply = await service.run_multi([AgentRequestText(prompt=prompt)])
await ctx.debug(f"Agent response '{reply}'")
if isinstance(reply, AgentReplyAny) and reply.media_type:
    meta: dict[str, Any] = {"media_type": reply.media_type}
    if isinstance(reply.content, dict):
        return ToolResult(structured_content=reply.content, meta=meta)
    meta["fastmcp"] = {"wrap_result": True}
    return ToolResult(structured_content={"result": reply.content}, meta=meta)
if isinstance(reply, AgentReplyText):
    return reply.response
if isinstance(reply, AgentReplyAny):
    return str(reply)
return "Non-text reply given"
```

- The `-> Any` annotation and the `ctx` logging are untouched. Verified against the pinned fastmcp
  (3.4.7): a dict return annotated `-> Any` already produces `structuredContent`, and a `ToolResult`
  carrying `meta` round-trips to a client intact.
- **An array payload cannot travel bare.** MCP's `structuredContent` is an object by specification,
  and fastmcp enforces it: `ToolResult(structured_content=[{"a": 1}])` raises
  `ValueError: structured_content must be a dict or None`. Since Decision 10 makes a v0.9.1 message
  sequence a first-class payload, the array travels under `result` — fastmcp's own convention for a
  non-object return (`fastmcp/tools/base.py:367`) — with the `fastmcp.wrap_result` flag a client
  reads to undo it (`fastmcp/client/mixins/tools.py:433-444`). Verified end to end: the client's
  `.data` is the array, `structuredContent` is a valid MCP object. This is MCP's constraint rather
  than an Agent Kernel envelope, so Decision 9 still holds.
- **Any reply without a media type** — text, image, or structured-but-unlabelled — still produces
  exactly the string it does today. That is why the three-way branch is spelled out here rather than
  collapsed to `str(reply)`: it reproduces the mapping `AgentService.run` applied (`core/service.py:156`)
  before this method stopped calling it, and `str(reply)` alone would surface
  `AgentReplyImage.__str__` where `"Non-text reply given"` used to go. That string is poor, and REST
  already returns the better one for the same reply — but changing it here is ungated, so image
  replies over MCP are a **Non-goal** (design.md §9) rather than a side effect of this change.
- **The key is `media_type` here and `mimeType` on A2A — deliberately, not an oversight.** A2UI
  publishes an A2A binding that names `mimeType`, so A2A uses A2A's word. MCP has no such binding, so
  `_meta` carries Agent Kernel's own name, matching the reply field and the REST response key.
- `_meta` is MCP's own slot for implementation metadata. The rejected alternative was wrapping the
  payload (`{"media_type": …, "content": …}`), which changes the shape the client receives.

### A2A — not touched

**A2A does not import today.** `ak-py/uv.lock` pins `a2a-sdk 1.1.2`, and in that venv
`import agentkernel.api.a2a.a2a` raises
`ImportError: cannot import name 'new_agent_text_message' from 'a2a.utils'`. Nothing is red because
no test imports the module.

**This issue changes nothing about it** — not `ak-py/pyproject.toml`, not `ak-py/uv.lock`, not
`api/a2a/a2a.py`, and it adds no A2A test. Fixing the import, porting to 1.x and carrying A2UI over
A2A are all the port issue's (design Decision 6).

An earlier draft capped the pin here, justified as giving the port characterisation tests to migrate
from. That does not hold: **1.x replaces the pydantic types with protobuf**, so every assertion such
a test could make (`msg.parts[0].root.text` and the like) is rewritten at the port regardless. What
was left was a backwards relock followed within days by a forwards one, and `pyproject.toml` churn in
a payload-carriage change.

For the port issue: the migration is roughly 60–90 lines across `core/builder.py`,
`api/a2a/handler.py` and `api/a2a/a2a.py` — `new_data_message` returns an `a2a_pb2.Message` with no
`model_dump`, and `AgentCard` has no `url` or `preferred_transport` (they become
`supported_interfaces`), so today's card raises `ValueError: Protocol message AgentCard has no "url"
field`. The five framework adapters are unaffected, verified. Groundwork:
[`research/a2a-datapart.md`](research/a2a-datapart.md).

### `integration/agui/mapping.py` — AG-UI

One `case "data_message"` above the `case _` fallback (`:67`), producing AG-UI's custom event with
`media_type` as the name and `content` as the value. Unmapped types already return `None`, so an
AG-UI client on an older mapper degrades rather than breaks.

### `integration/thread/recorder.py` — thread recording

`ThreadRecorder.post_run` (`:60`) stores `str(result)` into `ThreadMessage.content` (`:67`). Through
the queue, `AgentRunner` passes the already-built response body's `result` value
(`pipeline/agent_runner.py:55`), which for a labelled reply is now a **dict**, and `str()` on a dict
yields a Python repr — single quotes, `None`, `True`. The direct thread handler stores proper JSON
for the same reply. So the same agent, in the same thread store, would be recorded one way in
single-process mode and another through the queue, permanently.

**The two call sites pass different types, which is what makes this easy to get wrong.** Verified:

| Caller | `result` is | `str(result)` gives |
|---|---|---|
| `integration/thread/thread_chat.py:136` (direct) | an `AgentReply` **object** | `json.dumps(content)` — already correct |
| `integration/thread/thread_chat.py:178` (direct, streamed) | a `str` of joined deltas | itself — correct |
| `pipeline/agent_runner.py:55` (queue) | the response body's `result` **value** — a `dict` once labelled | a Python **repr** — the defect |

So the fix cannot be "always `json.dumps`": that would raise `TypeError` on the direct path's model
object. The normalisation becomes a method on the recorder — `ThreadRecorder._as_thread_content` —
rather than inline branching in `post_run`, so it has a name and a test:

```python
@staticmethod
def _as_thread_content(result: Any) -> str:
    """Render any reply form as the thread store's `str` content, without a Python repr."""
    if isinstance(result, str):
        return result
    if isinstance(result, (dict, list)):
        return json.dumps(result, default=str)  # the queue path's labelled reply
    return str(result)                          # an AgentReply — its __str__ is already json.dumps
```

**The dict branch is the one gate site that deliberately does not use `PayloadCodec.encode`.** It
mirrors `AgentReplyAny.__str__`'s own call instead, `default=str` included, because the two thread
paths must agree with each other before they agree with anything else: the direct handler stores
`str(reply)` and the queue runner stores this, for the same reply. For JSON-safe content the codec
and `default=str` produce identical bytes, so the choice only shows on a value that reached
`content` through one of the documented bypasses — there, thread history holds `str()`'s form while
the live reply carries ISO 8601. That divergence is accepted; two encodings of the same reply inside
one store is not. **It is not one of the gate sites, and that is the only deliberate exception.**

`ThreadMessage.content` stays `str` (`integration/thread/model.py:33`) — **labelling stored history
is a Non-goal**; this fixes the encoding only.

### Consumer changes

| Consumer | Change |
|---|---|
| Six framework adapters | **None.** They call `from_output` with no media type and are unaffected. Verified: no adapter sets or reads `media_type`. |
| `core/service.py:144` `AgentService.run` | **None.** Still returns `str`. MCP moves to `run_multi`; A2A and the CLI keep `run`. |
| `pipeline/ws/base.py` | **None.** `send(..., message: dict)` passes the response dict through as a JSON frame, so WebSocket gets the object form free. |
| Redis / Valkey response stores | **None, verified.** They re-serialise a body that is already JSON-native. |
| `pipeline/response_handler.py:68` | **None — deliberately.** The messaging integrations receive a Python repr for a labelled reply; they are text surfaces with no A2UI renderer, and pointing a labelled agent at one is the application's choice. Non-goal, recorded with the consequence spelled out. |
| Existing test fixtures and example clients | **None.** All unlabelled. |

### Config changes

One new block. **`_A2UIConfig`**, placed beside `_SandboxConfig` (`core/config.py:889`) and registered
on `AKConfig` beside `sandbox` (`core/config.py:1053`):

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
   becomes ISO 8601 rather than `str()`'s space-separated form; a `set` becomes a list; UTF-8
   `bytes` become their string; a non-string key becomes a string. A `Decimal` is **not** in the
   list — normalisation renders it as the same quoted string `default=str` did. *Justification:*
   the four encoders converge on one form (Piece 1). **This is the only behavioural change that is
   not gated on a media type**, and the only changelog line the design requires.
4. **`AgentReplyAny(content=...)` now raises `ValidationError` for an unserialisable object**, where
   it previously accepted it and `default=str` shipped `"<Row object at 0x…>"` to a client as data.
   *Justification:* raising at construction beats shipping a repr as data.
5. **`AgentReplyAny(content=...)` raises for `NaN` / `inf` / `-inf`.** *Justification:* Decision 8.
6. **`AgentReplyAny.content` accepts a top-level list.** Widening only, and reachable only by direct
   construction — `from_output` still returns `None` for a bare list, so no adapter's behaviour
   changes. *Justification:* Decision 10, without the ungated side effect widening `from_output`
   would have caused.
7. **The DynamoDB response store converts floats to `Decimal` on write and back on read.** A payload
   carrying a float previously failed the write outright. Round-tripped values are `float`/`int`, not
   `Decimal`, on every read path. *Justification:* the feature ships broken otherwise.
8. **Thread recording through the queue stores JSON rather than a Python repr for a labelled reply.**
   Unreachable today, since `result` is never a dict at that point. *Justification:* the two thread
   paths must not diverge permanently.
9. **MCP returns a `ToolResult` with `structuredContent` and `_meta` for a labelled reply.** Gated.
   *Justification:* Piece 4.
10. **A streamed run can emit a `DataMessage` before `MessageEnd`.** Only when an application hook
    produces one; nothing in the framework emits it. *Justification:* Piece 3.
11. **`stream_chunk` serialises in JSON mode.** Byte-identical for every event type that exists
    today. *Justification:* prevents a mid-stream raise.

**Non-changes — fixed on purpose:**

- `__str__`'s *code*, the `AgentReply` union, and every framework adapter.
- What MCP returns for an image reply. Still `"Non-text reply given"`, still without `image_data`,
  and still different from the string REST returns for the same reply. A Non-goal, not a guarantee
  worth keeping — see design.md §9.
- `AgentPausedReplyAny` (#606). It redeclares `content: dict` (`core/model.py:290`) and builds the
  value in a `model_validator(mode="after")`, so it bypasses `JSONPayload` on both counts — the
  bypass Decision 4 names. Accepted rather than fixed: its content is derived from strings and
  `interruption.model_dump(mode="json")`, so it is JSON-safe by construction and the annotation
  would have nothing to do. Applying it would mean an explicit `PayloadCodec.normalise` call inside
  the validator, since assignment there skips validation anyway.
- `AgentService.run`'s signature and return type (`str`).
- `ThreadMessage.content`'s type (`str`) and the thread read routes.
- `pipeline/response_handler.py`'s messaging path.
- The response dict for any reply without a `media_type` — byte for byte, including the
  deferred-schedule 202 acknowledgement (`core/chat_service.py:567` builds an `AgentReplyAny` with no
  media type).
- Every `result` example in the published docs (six files) and every `["result"]` read in the example
  test suites (seven, across four files) — all text or unlabelled.

---

## Error handling

| Failure | Surfaces as |
|---|---|
| Unserialisable value in `content` | `ValidationError` at construction, naming the field. Raised in the application's own code, not down the pipeline. |
| `NaN`/`inf` in `content` | `ValueError` from the validator with the offending key path, wrapped by pydantic into `ValidationError`. |
| A value reaching a serialisation gate through a bypass | Encoded by `PayloadCodec.encode` rather than raising `TypeError` and losing the message to retry exhaustion. |
| `a2ui` block absent or `enabled: false` | `A2UIPostHookFactory.get()` returns `NoOpA2UIPostHook`. No error, no log noise. |
| `A2UIPostHookFactory.get()` raises | Logged via `logging.getLogger("ak.a2ui.hook").exception(...)`; returns `NoOpA2UIPostHook`. The hook chain never breaks the runtime. |
| Reply body is not JSON | Returned untouched and unlabelled — the normal prose case, not an error. Not logged: it is most turns. |
| Reply body parses to a scalar | Returned untouched. Guarded explicitly so `JSONPayload` never sees it. |
| Reply parses but is not valid A2UI | Labelled and forwarded. Agent Kernel does not validate; the renderer rejects it, which is the correct and visible outcome. |
| `DataMessage` with an unsafe value | Cannot occur — `JSONPayload` rejects at construction, before the stream. |
| DynamoDB write of a float | Converted to `Decimal`; no longer raises. |
| MCP host ignores `_meta` | The client receives the payload without knowing its format. Accepted (Decision 9) — a host integration problem, not a reason to invent a wrapper. |
| A2A used at all | Unchanged: the module does not import against the pinned SDK. The port issue's to fix. |

---

## Testing

Run with `cd ak-py && uv run pytest`.

### New files

**`tests/test_payload.py`** — `PayloadCodec` directly, both halves.

- **Convergence, the whole rule in one assertion:** a pydantic model with `datetime`/`Decimal`/`UUID`
  fields through `from_output`, and a plain dict of the same values through
  `AgentReplyAny(content=...)`, produce **equal** `content`.
- Parameterised coercion: `datetime`, `date`, `Decimal`, `UUID`, `Enum`, `set`, `bytes`, non-string
  keys.
- Raises: an arbitrary object; `NaN`; `inf`; `-inf`.
- A top-level list validates; a scalar does not. `from_output` still returns `None` for a bare list
  — pinned, because widening it is the tempting change that breaks back-compat.
- **The bypasses, pinned as tested behaviour:** `model_copy(update={"content": ...})` does *not*
  normalise, and neither does in-place mutation. Pin them so nobody builds on a guarantee that is
  not there.
- **`encode` separately from `normalise`:** a body holding a `datetime` that bypassed the validator
  still encodes rather than raising — the property every gate depends on.
- **`QueueMessage.body` is JSON text**, asserted on the envelope itself: a dict and a list encode on
  validation, a `str` is byte-identical to what the sender passed, an empty default stays `""`, and
  a scalar is still a `ValidationError`. Plus `_send_to_output` handing the envelope a dict, which
  is what makes dropping its own `encode` call safe.
- **The response body is JSON-safe**, which is the invariant the seams rest on: a reply whose
  `content` was replaced by `model_copy` still comes back out of `build_response` normalised, so
  `json.dumps(body)` equals `PayloadCodec.encode(body)` — written that way deliberately, because
  what a new seam's author is allowed to assume is the thing worth pinning. An unlabelled reply is
  untouched, so the coercion costs nothing on the common path.

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
  object with `media_type` set — with **no application post-hook anywhere in the test**. The
  `Runtime.run` half of that claim lives in `tests/test_runtime.py`, which is where the registration
  can actually be exercised; this file builds the hook directly.

**`tests/test_cross_surface_parity.py`** — one labelled structured reply asserted to arrive with the
same content and the same label on REST, WebSocket, MCP and AG-UI, plus an **array** payload
asserted to reach every surface unchanged except MCP, which is the one carrier that cannot hold it
bare. A2A joins when the port issue adds the data part. Nothing like it exists today; it is what makes §3's claim checkable and what
catches a future surface regressing to an early encode. **The fixture must carry a `datetime` and a
`Decimal`** — parity on a payload that was never at risk proves nothing.

### Changed files

| File | Change |
|---|---|
| `tests/test_model.py` | `media_type` defaults to `None` and round-trips; `content` accepts a list; `__str__` parameterised — byte-identical for JSON-safe content and for a `Decimal`, the pinned new output for `datetime`, `set` and a non-string key, and **raises** for `NaN`. |
| `tests/test_chat_service_core.py` | `build_response` matrix: labelled → dict + `media_type`; unlabelled structured, text, image and the non-reply fallback → unchanged strings. Plus the regression test for the gap Copilot found: build a response for a reply whose content carried a `datetime`, then assert `json.dumps(response_body)` succeeds — reproducing `agent_runner._send_to_output`'s exact call. |
| `tests/test_api_http.py:400` | `TestResponseBuilderStructuredResult.test_structured_result_serialized_as_json_string` pins `response["result"] == json.dumps(content)` today. It becomes a matrix — **that exact assertion must keep passing** for the unlabelled case, with a labelled sibling asserting the dict. This is the back-compat guarantee, tested directly. |
| `tests/test_chat_service_streaming.py` | A `DataMessage` chunk serialises; `stream_chunk` in JSON mode is byte-identical for existing event types. |
| `tests/test_stream_events.py` | `DataMessage` round-trips through the discriminated union on `type`. |
| `tests/test_agui_mapping.py` | `data_message` → AG-UI custom event; an unknown type still returns `None`. |
| `tests/test_pipeline_agent_runner.py` | A labelled reply reaches the output queue carrying a `datetime` and a `Decimal` (the bare `json.dumps` no longer raises), and so does an array payload. The thread half of the same path lives in `tests/test_thread_pipeline_recording.py`, beside the thread-manager fixtures it needs: a labelled reply is recorded as JSON, not a Python repr. |
| `tests/test_thread_integration.py` | The queue path and the direct path record the **same bytes** for the same labelled reply. (Planned for `test_thread_runner.py`; it belongs with the other `_as_thread_content` cases.) |
| `tests/test_shared_drivers.py` — plus `DynamoDecimalCodec` round-trip cases of its own | A payload carrying a float is stored without raising **and reads back as a `float`, not a `Decimal`** — asserted by a `json.dumps` on the polled record, which is what `rest_lambda.py:288` does and what would fail if only the write side were fixed. |
| `tests/test_api_mcp.py` | A labelled reply produces `structuredContent` plus `_meta`; an **array** payload produces `{"result": [...]}` with the `fastmcp.wrap_result` flag, asserted both on the `ToolResult` and through a real client whose `.data` is the array again; an unlabelled structured reply, a text reply and an image reply each produce today's string. |
| `tests/test_config.py` | The `a2ui` block loads, defaults to disabled, and accepts `AK_A2UI__*`. |
| `tests/test_websocket_service_broadcast.py` | The AWS push serialises through the codec: a reply body carrying a `datetime` and a `Decimal` pushes as JSON, and an ordinary body is byte-identical to `json.dumps`. The gate runs on every push, so it may not change the bytes for anyone else. |
| `tests/test_runtime.py` | The capability through `Runtime.run`, which is where the registration in `_get_system_post_hooks` is the thing under test: a JSON reply arrives labelled with no application hook anywhere, prose and an out-of-scope agent are left alone, `enabled: false` changes nothing, and the output guardrail receives the reply **before** the label is applied. |

**Riskiest consumer.** `pipeline/agent_runner.py` changes shape the most for a labelled reply — it
feeds the output queue *and* thread recording from the same value. `tests/test_pipeline_agent_runner.py`
exists and covers it; both new assertions go there rather than into a new file.

### Example

One runnable example under `examples/`: an agent with its own catalog in its instructions, the `a2ui`
block turned on, and the payload arriving over plain REST with no UI framework involved. Its
`app_test.py` asserts `media_type` is present and `result` is an object — the only example test in the
repo that reads a non-string `result`.
