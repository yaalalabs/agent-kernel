# #710: AG-UI on the queue pipeline — Implementation Spec

How `design.md` is built. One new handler class, one new capability on two response stores, and a
typed envelope that carries the client's inbound values across the queue hop. `design.md` is the
requirements source; every section below traces to one of its numbered areas.

The change is additive: `AGUIRequestHandler` and its direct SSE path are untouched, no configuration
field is added, and a queue message without `ATTR_AGUI` behaves exactly as before.

## Design

### 1. The marker — `pipeline/envelope.py`, `pipeline/agent_runner.py`

```python
# envelope.py, beside the existing constants
ATTR_AGUI = "agui"
```

```python
# agent_runner.py:27 — the allowlist _send_to_output filters through
_FORWARDED_ATTRIBUTES = (ATTR_REQUEST_ID, ATTR_USER_ID, ATTR_ENDPOINT_URL, ATTR_INTEGRATION, ATTR_AGUI)
```

Rule: **an attribute the Response Handler reads must be in the allowlist; an attribute only the
runner reads must not be.** `ATTR_INTEGRATION` and `ATTR_AGUI` are the first kind;
`ATTR_THREAD` is the second (`agent_runner.py:137` consumes it before the output message exists).
`_is_forwarded` (`agent_runner.py:30-32`) needs no change — it already ORs the tuple with the
`reply_` prefix.

### 2. Response store sharedness — `pipeline/response_store/`

`ResponseStore` gains one predicate beside `supports_chunk_streaming`:

```python
# base.py, next to the existing capability block
@property
def shared(self) -> bool:
    """Whether a process other than the writer can read what this store holds.

    Chunk streaming says the store *can* carry a stream; this says a second process can read
    it. A queue topology that runs the agent in another process needs both.
    """
    return True
```

`InMemoryResponseStore` overrides it to `False`; `redis`, `valkey` and `dynamodb` inherit `True`.
Polarity and shape copy `WSConnectionStore.shared` (`core/session/base.py:22`) and its one override
(`core/session/in_memory.py:23`), so a bring-your-own store answers for itself and the default is the
safe one for an external service.

### 3. Chunk streaming on the shared stores

`redis.py` and `valkey.py` are today byte-identical apart from their driver import. Rather than write
chunk streaming twice, the shared body is lifted into a new `_RedisLikeResponseStore`, mirroring
`_RedisLikeThreadStore` (`integration/thread/store/redis_like.py:24`) — the house rule that two
classes sharing logic get a base class rather than a copy.

```
pipeline/response_store/
├── base.py          ResponseStore: + shared
├── redis_like.py    NEW — _RedisLikeResponseStore: the whole body, driver injected
├── redis.py         RedisResponseStore(_RedisLikeResponseStore): constructs RedisDriver
├── valkey.py        ValkeyResponseStore(_RedisLikeResponseStore): constructs ValkeyDriver
├── in_memory.py     + shared = False
└── dynamodb.py      unchanged
```

Chunk state is one list per request, separate from the record key:


| Key                           | Holds                                  |
| ----------------------------- | -------------------------------------- |
| `{prefix}{request_id}`        | the existing single record (unchanged) |
| `{prefix}chunks:{request_id}` | the chunk list, TTL from the driver    |


```python
def supports_chunk_streaming(self) -> bool:
    return True

def add_chunk(self, request_id: str, chunk: Dict) -> None:
    key = self._chunk_key(request_id)
    self._driver.rpush(key, json.dumps(chunk))
    self._driver.expire(key)                      # no-op when the driver's ttl is 0

def stream(self, request_id: str, chunk_timeout: Optional[float] = None) -> Iterator[Dict]:
    timeout = self._chunk_timeout(chunk_timeout)
    key = self._chunk_key(request_id)
    try:
        while True:
            raw = self._driver.blpop(key, timeout)
            if raw is None:
                raise TimeoutError(f"No stream chunk received for request_id '{request_id}' within {timeout} s")
            if raw == self._CLOSE_SENTINEL:
                return
            chunk = json.loads(raw)
            yield chunk
            if chunk.get("done"):
                return
    finally:
        self._driver.delete(key)

def close_stream(self, request_id: str) -> None:
    key = self._chunk_key(request_id)
    self._driver.rpush(key, self._CLOSE_SENTINEL)   # unblock a parked reader
    self._driver.expire(key)
```

Three rules this encodes, each matching `InMemoryResponseStore`'s existing semantics
(`in_memory.py:65-110`) so the contract suite passes unchanged against all three:

1. **The terminal chunk ends the stream.** A chunk with `done` returns after being yielded.
2. `close_stream` **unblocks a parked reader** rather than closing the generator, because the reader
  may be mid-`blpop` on a worker thread. The in-memory store uses a sentinel object; the redis-like
   body uses a reserved string constant, since the list holds JSON.
3. `chunk_timeout` **defaults to the store's** `retry_count x delay` **budget**, the same fallback
  `in_memory.py:77-83` computes, lifted to a `_chunk_timeout` helper on the ABC so all three share it.



#### The driver addition — `core/util/driver/redis_like.py`

One method, in the shape of its neighbours (`rpush` at `:232`, `lpop` at `:242`):

```python
def blpop(self, key: str, timeout: float) -> Optional[str]:
    """Removes and returns the first element, blocking until one arrives or the timeout expires.

    :param key: The list key.
    :param timeout: Max seconds to block. Must be > 0; a redis timeout of 0 blocks forever.
    :return: The popped element, or None on timeout.
    """
    self._log.debug(f"BLPOP {key}")
    item = self.client.blpop([key], timeout=max(timeout, 0.001))
    if item is None:
        return None
    value = item[1]                                  # (key, value)
    return value.decode() if isinstance(value, (bytes, bytearray)) else value
```

`_RedisLikeDriver` is shared by both backends (`redis_like.py:16-19`, the valkey client being a
`redis-py` fork), so one method serves both. The `max(timeout, 0.001)` guard matters: redis reads a
timeout of `0` as "block forever", which would hang a worker thread past any budget.

Drivers never read `AKConfig` — the timeout arrives as a parameter, per the shared-driver rule.

### 4. Agent Runner — `pipeline/agent_runner.py`

`AgentRunner.process` gains one branch at the top, the mirror of `StreamAgentRunner.process`'s
existing `ATTR_INTEGRATION` fallback (`:212-214`):

```python
def process(self, message: QueueMessage) -> None:
    if message.attributes.get(ATTR_AGUI):
        return self._process_agui(message)
    ...unchanged...
```

`StreamAgentRunner` inherits it, so the branch is reached whatever class `IOHandler` selected — which
is the point: the app's `execution.mode` no longer decides whether an AG-UI run streams.

`_process_agui` is a method on `AgentRunner`, not a separate class: it is one execution path of the
same component, and it reuses `_resolve_request_metadata` and `_send_to_output` unchanged.

```python
def _process_agui(self, message: QueueMessage) -> None:
    from ..integration.agui.run_input import AGUIRunEnvelope   # lazy: integration extra
    from ..integration.agui.state import AGUIState

    body = AGUIRunRequest.model_validate(json.loads(message.body))
    request_id = self._resolve_request_metadata(message, body)

    handler = self._chat_service.prepare_agent_handler(body.session_id, body.agent)
    session = handler.service.session
    AGUIRunEnvelope.apply(session, body.agui)        # state -> nv_cache, the other two -> v_cache
    state_before = AGUIState.snapshot_state(session)

    chunk_count = 0
    for chunk in handler.run_stream_sync(body.requests, acting_user_id=body.user_id):
        self._send_to_output(message, json.loads(chunk.model_dump_json()), status_code=None,
                             dedup_suffix=f"{message.receive_count}-{chunk_count}")
        chunk_count += 1

    state_after = AGUIState.read_state(session)
    if state_after != state_before:
        self._send_to_output(message, {"agui_state": state_after}, status_code=None,
                             dedup_suffix=f"{message.receive_count}-{chunk_count}")
```

Four things it deliberately does **not** do:

- **No** `ATTR_USER_ID` **check.** The guard at `:218` is the WebSocket-entered marker and applies to
`StreamAgentRunner.process`, which this branch returns before reaching.
- **No** `process_stream_chat_sync`**.** That wrapper hides the `AgentHandler`, and this path needs the
session between load and run — the documented reason `prepare_agent_handler` exists
(`core/chat_service.py:362-370`).
- **No thread recording.** `_record_thread_reply` is not called; `ATTR_AGUI` is not `ATTR_THREAD`.
- **No session write at the end.** `Runtime.stream` already stores the session and clears the
volatile cache in its `finally` (`core/runtime.py:364`, `:372`).

Both imports are lazy inside the method, the rule `_record_thread_reply` (`:125-150`) and
`ResponseHandler._outbound_adapter` already follow: a runner process without the `agui` extra must
not pay for it at module scope.

### 5. Response Handler — `pipeline/response_handler.py`

One branch, ahead of the mode branch, beside the existing integration dispatch (`:54-57`):

```python
def process(self, message: QueueMessage) -> None:
    integration = message.attributes.get(ATTR_INTEGRATION)
    if integration:
        self._deliver_integration(message, integration)
        return
    if message.attributes.get(ATTR_AGUI):
        self._store_chunk(message)
        return
    ...mode branch unchanged...
```

`_store_chunk` is reused as-is (`:211-218`) — it already resolves the request id, checks
`supports_chunk_streaming()` and calls `add_chunk`. No AG-UI-specific store method is needed.

`on_permanent_failure` gains the matching branch before its own mode branch (`:87-104`), writing one
terminal chunk so the edge closes the run with exactly one `RunError`:

```python
if message.attributes.get(ATTR_AGUI):
    store = self._get_store()
    if store.supports_chunk_streaming():
        store.add_chunk(request_id, {"error": "The run failed after repeated attempts", "done": True})
    return
```

Fixed text, not the exception's — the same CodeQL `py/stack-trace-exposure` rule
`request_handler.py:314-320` already follows.

### 6. The inbound envelope — `integration/agui/run_input.py`, `core/model.py` consumers

```python
class AGUIRunEnvelope(BaseModel):
    """The client's per-run values, carried on the queue body rather than through the session."""

    state: Optional[dict] = None
    forwarded_props: Optional[dict] = None
    context: Optional[list[dict]] = None

    @staticmethod
    def build(run_input: "RunAgentInput") -> "AGUIRunEnvelope":
        """Edge half of the former set_agui_session_keys: validate and collect. Raises the 400s."""

    @staticmethod
    def apply(session: Session, envelope: Optional["AGUIRunEnvelope"]) -> None:
        """Runner half: write through the AGUIState accessors, in the caches AG-UI chose."""


class AGUIRunRequest(BaseRunRequest):
    """BaseRunRequest plus the AG-UI envelope. Typed, not an extra: see core/model.py:275-289."""

    agui: Optional[AGUIRunEnvelope] = None
```

`set_agui_session_keys` (`run_input.py:61-76`) splits along its existing seam: the validation and the
two `HTTPException(400)`s stay on the edge in `build`, the three `AGUIState` writes move to `apply`.
The direct handler calls `AGUIRunEnvelope.apply(session, AGUIRunEnvelope.build(run_input))` so both
execution models share one definition of which cache each field lives in — `AGUIState` remains the
only module that knows (`state.py:22-23`).

`AGUIRunRequest` lives in `integration/agui/`, not `core/model.py`: AG-UI is an optional extra and
core must not grow a field for a surface that may not be installed. `RequestProducer.enqueue` takes a
`BaseRunRequest` and calls `model_dump(exclude_none=True)` (`pipeline/producer.py:46-49`), so a
subclass needs no producer change.

`RequestBuilder.known_fields` (`core/chat_service.py:127-143`) gains `"agui"`. Belt and braces: the
AG-UI path always passes a prebuilt `requests` list, so `RequestBuilder` is skipped — the entry means
that guarantee does not rest on a call-site invariant holding forever.

### 7. The queue-mode handler — `integration/agui/pipeline.py` (new)

```python
class AGUIPipelineRequestHandler(AGUIRequestHandler):
    """Queue-mode AG-UI: enqueue the run, stream the reply back from the response store."""

    requires_pipeline = True

    def __init__(self, authoriser=None, auth_validator=None):
        super().__init__(authoriser, auth_validator)        # every check the direct handler makes
        self._validate_topology()
        self._store = ResponseStoreFactory.create()
        self._producer = RequestProducer()

    async def _run(self, agent_name: str, request: Request) -> StreamingResponse:
        agent, run_input, requests = self._prepare(agent_name, request)   # shared with the direct path
        envelope = AGUIRunEnvelope.build(run_input)
        requests = AttachmentStorageManager.offload(requests)
        request_id = uuid4().hex
        self._producer.enqueue(
            AGUIRunRequest(session_id=run_input.thread_id, user_id=self._resolve_user(request),
                           requests=requests, agui=envelope),
            request_id=request_id,
            attributes={ATTR_AGUI: "1"},
            group_id=run_input.thread_id,
        )
        encoder = EventEncoder(accept=request.headers.get("accept"))
        return StreamingResponse(self._events_from_store(encoder, request_id, run_input),
                                 media_type=encoder.get_content_type())
```

`_prepare` is the extracted edge half of `AGUIRequestHandler._run` (`handler.py:177-205`): authorise,
resolve the agent, parse the body, map to requests. Both handlers call it, so the 404/400 contract
cannot drift. What stays behind in the direct handler is everything from `prepare_agent_handler`
onward (`handler.py:206-220`) — the queue-mode handler creates no session.

`_events_from_store` mirrors `AGUIRequestHandler._events` (`handler.py:222-289`) with one difference:
the event source is `store.stream(request_id)` drained through `asyncio.to_thread`, the shape
`RequestHandler._sse_stream` already uses (`request_handler.py:306-334`), including its
`finally: close_stream(request_id)`. The bracket is unchanged — `RunStarted` first, exactly one of
`RunFinished`/`RunError` last — and a chunk carrying `agui_state` maps to `StateSnapshotEvent`
instead of going through `AGUIMapper`.

Mounting: `IOHandler.run(handlers=[AGUIPipelineRequestHandler(...)])`. AG-UI owns `agui.prefix`, so it
collides with no pipeline route and needs no `IOHandler` change.

Export: `integration/agui/__init__.py` gains `AGUIPipelineRequestHandler`. The module imports
`pipeline` at module scope, which is allowed — `integration/adapter` already does
(`integration/adapter/producer.py:8-10`); the forbidden direction is `pipeline` → `integration`.

### 8. Preconditions — `_validate_topology`

```python
def _validate_topology(self) -> None:
    store = ResponseStoreFactory.create()
    transport = QueueTransportFactory.resolve_type()
    if not store.supports_chunk_streaming():
        raise AKConfigError(
            f"AG-UI queue mode needs a chunk-streaming response store: '{type(store).__name__}' cannot "
            f"stream chunks; configure execution.response_store.type as redis or valkey"
        )
    if transport != "in_memory" and not store.shared:
        raise AKConfigError(
            f"response store '{type(store).__name__}' is process-local but the queue transport is "
            f"'{transport}', so the agent runs in another process; configure redis or valkey"
        )
    # The session holds the conversation. A broker means a fleet of runners, so turn 2 can land on a
    # different one than turn 1 and read an empty dict; a restart empties it too. The agent then
    # answers with no history and no error. A single replica happens to work, until it is scaled or
    # redeployed — which is why the check reads the transport rather than a replica count.
    if transport != "in_memory" and AKConfig.get().session.type.lower() == "in_memory":
        raise AKConfigError(
            f"session store 'in_memory' is single-process only, but the queue transport is "
            f"'{transport}'; use redis, valkey, dynamodb, cosmosdb or firestore"
        )
```

Message shape copies `ScheduleManager._validate_store_topology` (`schedule/manager.py:392-395`): name
what is wrong, name the transport, name the way out. The third check compares the literal
`in_memory` and lets a dotted path through — the accepted blind spot `design.md` §6 records, matching
`manager.py:387`.

### Consumer changes


| File                          | Change                                                                                                  | Verified unchanged                                                      |
| ----------------------------- | ------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------- |
| `pipeline/request_handler.py` | `_reject_unroutable`'s STREAM branch (`:288-296`) also requires `store.shared` on a broker transport    | every other route; the `rest_sync`/`rest_async` paths                   |
| `integration/agui/handler.py` | `_run` splits; `_prepare` extracted; `set_agui_session_keys` becomes `AGUIRunEnvelope.build` + `.apply` | routes, `_resolve_agent`, `_warn_if_unreadable`, `_events`, the bracket |
| `integration/agui/state.py`   | none — it stays the only module that knows the cache per field                                          | all accessors                                                           |
| `pipeline/io_handler.py`      | **none.** Its REST-only shared-store guard is left alone; recorded as a follow-up                       | all fail-fasts                                                          |




### Config changes

**None.** No new field, no new block, no new `enabled` flag or `type` selector. `_AGUIConfig`
(`core/config.py:873-882`) keeps every field, name, type and default; the handler reads
`execution.response_store` and `session` through the existing factories. Existing YAML and `AK_*`
variables keep working unchanged, and mounting the sibling is what selects the queue path.

### Behavioural changes

1. `_FORWARDED_ATTRIBUTES` **gains a member.** Output messages from an `ATTR_AGUI` input now carry the
  attribute. No existing consumer branches on it, so no other traffic changes. *Intentional: §1.*
2. `ResponseStore` **gains a** `shared` **property.** Default `True`, so every existing store — including
  a bring-your-own one — answers as it did implicitly. *Intentional: §2.*
3. `redis`**/**`valkey` **response stores answer** `True` **to** `supports_chunk_streaming()`**.** They previously
  raised `NotImplementedError` from the three methods. *Intentional: §3.*
4. `RequestHandler`**'s STREAM SSE route now serves redis/valkey**, where it answered HTTP 400. On a
  broker with an explicitly configured `in_memory` store it now returns 400 where it previously
   accepted the request and hung to the timeout. *Intentional: §8 of the design — strictly more
   working in the first case, strictly clearer in the second.*
5. `RedisResponseStore`**/**`ValkeyResponseStore` **become subclasses of a shared body.** Same public
  surface, same key layout, same constructor signature. *Intentional: house rule against duplication.*

**Non-changes.** `AGUIRequestHandler`'s routes, gates and event bracket; the `agui` config block; the
record key layout and `add_message`/`get_record` semantics of every store; `StreamChunk`
(`core/model.py:180-194`) gains no field; `dynamodb.py` and `in_memory.py`'s chunk behaviour;
`ATTR_THREAD`'s deliberate absence from the allowlist; `IOHandler`.

## Error handling


| Failure                                                | Surfaces as                                                                                            |
| ------------------------------------------------------ | ------------------------------------------------------------------------------------------------------ |
| Response store cannot stream chunks                    | `AKConfigError` at handler construction, naming the store                                              |
| Response store is process-local on a broker            | `AKConfigError` at construction, naming store and transport                                            |
| `session.type: in_memory` on a broker                  | `AKConfigError` at construction, naming the transport                                                  |
| Handler mounted on a bare `RESTAPI.run`                | `AKConfigError` from `_reject_pipeline_only_handlers` (`api/http.py:117-131`), via `requires_pipeline` |
| Oversized envelope                                     | HTTP 400 at the edge, before enqueue, naming the field and the budget                                  |
| Audio/video content                                    | HTTP 400 from `AGUIRunInput._to_request` (`run_input.py:122-129`), unchanged                           |
| Attachment with multimodal disabled or `session_cache` | The caller-facing message `AttachmentStorageManager.offload` already produces                          |
| Runner exhausts retries                                | One terminal error chunk → exactly one `RunError`, fixed text                                          |
| No chunk within the budget                             | `TimeoutError` → one error chunk on the socket, fixed text (`request_handler.py:314-320`'s rule)       |
| Client disconnects mid-stream                          | `finally: close_stream(request_id)`; the runner completes and its chunks expire by TTL                 |
| `agui` extra missing                                   | `ValueError` naming the extra, inherited from `AGUIRequestHandler.__init__`                            |


The two failures with no error path by design are recorded in the design's §8: duplicate events on
redelivery, and the loss window when the API replica dies mid-run.

## Testing

Run: `cd ak-py && uv run pytest`.

### New files


| File                                    | Asserts                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| --------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `pipeline/response_store/testing.py`    | `ResponseStoreContract` — the reusable suite. Subclass, implement `make_store()`. Pins chunk order, the terminal `done` chunk ending the stream, `close_stream` unblocking a reader parked mid-wait, a reader that attaches after the writer finished, the per-chunk timeout, and that `shared` is declared. Docstring states that `add_chunk` is **not** required to be idempotent — duplicate delivery is a reader concern (design §8), so no BYO store inherits that obligation by accident. |
| `tests/test_response_store_contract.py` | The contract against `in_memory`, and against `redis`/`valkey` through a fake redis-like client injected as `store._driver._client`, the shape `test_schedule_store.py` already uses.                                                                                                                                                                                                                                                                                                           |
| `tests/test_response_store_redis.py`    | Key layout, TTL refresh on `add_chunk`, the `blpop` sentinel path. There is no redis response-store test today — only valkey.                                                                                                                                                                                                                                                                                                                                                                   |
| `tests/test_agui_pipeline.py`           | The handler end to end over `in_memory`: the bracket holds; both preconditions raise; the marker survives; attachments are offloaded; the envelope reaches the tools.                                                                                                                                                                                                                                                                                                                           |




### Changed files


| File                                      | Change                                                                                                                                                                                                                                           |
| ----------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `tests/test_pipeline_agent_runner.py`     | New: an `ATTR_AGUI` message routes to the streaming path under `rest_sync`, and its output messages still carry the marker — mirroring the `ATTR_INTEGRATION` assertion at `:192`.                                                               |
| `tests/test_pipeline_response_handler.py` | New: the AG-UI branch precedes the mode branch, **with and without** `ATTR_USER_ID`, parametrised over all four modes — the shape of `test_the_integration_branch_precedes_the_mode_branch` (`:227`). Plus the permanent-failure terminal chunk. |
| `tests/test_response_store_in_memory.py`  | Subclass the contract; assert `shared is False`.                                                                                                                                                                                                 |
| `tests/test_response_store_valkey.py`     | Subclass the contract; assert `shared is True`.                                                                                                                                                                                                  |
| `tests/test_pipeline_request_handler.py`  | STREAM + broker + unshared store returns HTTP 400 instead of hanging.                                                                                                                                                                            |
| `tests/test_shared_drivers.py`            | `blpop` returns the value, returns `None` on timeout, and never passes a zero timeout to the client.                                                                                                                                             |




### The decisive cases

These four fail against the design as originally written and pass against it as specified — they are
the reason each requirement exists, and each maps to a PR review finding:

1. **Capability is not sharedness.** Configure a broker transport plus an explicit
  `execution.response_store.type: in_memory`. In one test assert the factory returns an
   `InMemoryResponseStore`, that `supports_chunk_streaming()` is `True`, that `shared` is `False`,
   and that constructing the handler raises `AKConfigError`. The third assertion is the point.
2. **The marker survives the hop.** An `ATTR_AGUI` input message produces output messages still
  carrying it. Without the allowlist entry the Response Handler takes the mode branch.
3. **The envelope reaches the tools, and keeps its lifetime.** A run carrying `forwarded_props` and
  `context`, with a stubbed agent reading both mid-run, sees both non-empty. Then assert the
   persisted session record carries neither key, and that a second run on the same `threadId` sending
   no `forwarded_props` reads `{}`. Proves they crossed the queue without becoming non-volatile.
4. **State baseline ordering.** A run carrying inbound `state` whose agent never calls
  `update_agui_state` emits **no** `StateSnapshotEvent` — proving `state_before` is snapshotted
   after the envelope is applied, not before.

Supporting: a dotted-path response store declaring `supports_chunk_streaming() -> True` constructs
successfully on a broker, asserted so the accepted blind spot stays deliberate; and an
attachment-bearing run enqueues a body whose `requests` carry `AgentRequestAttachmentRef` with no
inline base64.