# #928: Realtime calls follow the AK run lifecycle: session, context and tracing — Implementation Spec

This spec details [design.md](design.md). Two changes: a call stores its session once when it ends normally, as
`Runtime.stream` does, writing off the shared pool loop; and a call is traced by a traced realtime runner that the `Module` picks, as text runs
are traced. No new config, no adapter behaviour change, no new pool class.

Line numbers cite `feature/927-realtime-hooks` at `07821ddfb` and were read, not remembered. Paths are relative to
`ak-py/src/agentkernel/` unless they start with `docs/`, `tests/` or a third-party package name.

## Design

### 1. `Runtime` (`core/runtime.py`): `activate`

- `activate(agent, session)`: a public context manager. It sets `Session.current_session` and enters `agent._activate()`, and resets both on exit, even after an exception. It takes no session lock and only sets context variables.
- The end steps are not shared: the pool calls `session._unpublish_run()` and `session.get_volatile_cache()._clear_all()` itself, as the inline lines in `run()` and `stream()` do (#603 section 8.4).
- `run()` and `stream()` call `activate` around the hook and runner span. Behaviour is unchanged.
- Identity publication is not touched: `Runtime._publish` stays private, called by `run()`, `stream()` and the pool (`pipeline/realtime_pool.py:112`), as #603 section 8.4 specifies.
- No store method is added: the pool calls `runtime.sessions().store(session)`, the call `run()` and `stream()` make (`:546`, `:627`).

### 2. `RealtimeConnection` (`pipeline/realtime_pool.py`)

No new class. One new instance attribute:

```python
self._failed = False   # set by _fail and fail_to_connect: no store at close
```

#### 2.1 Unchanged lifecycle steps

- `_connect` and each hook call (`_emit_event`, `_process_audio`, `_process_text`) enter `Runtime.activate`; the pool's own `_hook_context` is gone. `ToolContext(...).set()` / `reset()` stay.
- `Runtime._publish` (`:112`) and `Session._publish_run`'s docstring (`core/base.py:270-272`) are unchanged.

#### 2.2 Storing the session at the end of the call

- Once, in `close()`, after `adapter.disconnect()` and before the identity and volatile cache are cleared: the order `Runtime.stream` uses (store, then the `finally` that ends the run). Disconnecting first lets the adapter finish its own writes (ADK flushes its session service, `framework/adk/adk.py:1125-1126`).

  ```python
  try:
      await self.adapter.disconnect()
  finally:
      try:
          if not self._failed:
              await self._store_session()
      finally:
          if self._principal_published:
              self.session._unpublish_run()
          self.session.get_volatile_cache()._clear_all()
  ```

- `_store_session()`: `await asyncio.to_thread(self.runtime.sessions().store, self.session)`. A failure is logged with its traceback (`ERROR`) and not raised, so the identity and the volatile cache are still cleared.
  - A turn's write is a copy (`_save_turn`: each durable key pickled with `BinarySerde` on the pool loop, where every change to the session happens, so ADK or a hook cannot change it mid-copy; unpickled and written on the worker thread; each write waits for the previous one, so writes land in turn order with no lock); the write at close is the live session and waits for the last turn write. A failed call waits for that write too, but stores nothing.
  - On a worker thread, not the loop: the pool loop serves every call in the process (`:461-465`), and a store is synchronous network I/O. A slow write delays only this call's close.
  - Accepted risk: an input chunk whose hooks are still running (`_process_audio` / `_process_text`, scheduled from a consumer thread) could change the session while the thread writes it. The native session and the pacing task have already stopped.
- No store after a failure: `_fail` (`:203`) and `fail_to_connect` (`:220`) set `self._failed = True` before anything else, as `Runtime.stream` stores nothing for a halted run.
- Normal ends, which store: `end_session` (`:650-663`), idle eviction (`:552-554`), shutdown (`_close_all`, `:557-567`), and a close during startup (`:145-150`).
- Stale eviction in `get_connection` (`:582-592`) closes a connection that is already `closed`. That is a failed one, so `_failed` is already set; a connection closed by `end_session` is popped first (`:653`) and never reaches it.
- `close()` runs once (`_disconnecting`, `:439-441`), so a call is stored at most once.
- A finished turn stores a copy: `done` reaches `_save_turn` after its `MessageEnd` passed the post-hooks, so a halting post-hook (which fails the call first) leaves that turn unstored.

#### 2.3 Unchanged

- No lock. Volatile cache cleared once, at close, after the store, as in `Runtime.stream`. Principal publication per input. `ToolContext` built by the pool. Hook calls, pacing, the `MessageEnd` sequence, `_queued_audio`, the reconnect back-off.

### 3. Tracing

#### 3.1 The contract (`trace/base.py`)

No OpenTelemetry import here: `opentelemetry` is not a core dependency (`pyproject.toml:15-21`).

```python
class RealtimeCallSpan(ABC):
    """One trace span over a realtime call: opened around connect, ended at disconnect."""

    @abstractmethod
    def opened(self) -> AbstractContextManager[None]:
        """Start the span and make it current, with the provider's session tagging, for the block.
        Entered once, around connect: tasks started inside inherit it. The span stays open after the block."""

    @abstractmethod
    def fail(self, message: str) -> None:
        """Mark the span as failed."""

    @abstractmethod
    def end(self) -> None:
        """End the span. Safe to call twice, and when opened() was never entered or raised."""


class TracedRealtimeRunner(RealtimeRunner):
    """Base of every traced realtime runner: one RealtimeCallSpan per call. Listed before the framework's
    realtime runner in the bases, e.g. class X(TracedRealtimeRunner, OpenAIRealtimeRunner)."""

    SPAN_NAME: ClassVar[str]

    @abstractmethod
    def _start_call_span(self, session: Session, agent: Agent) -> RealtimeCallSpan: ...
```

- `TracedRealtimeRunner.__init__(*args, **kwargs)` calls `super().__init__(*args, **kwargs)` and sets `self._call_span = None`. With the bases in the order above, the MRO reaches the framework runner's `__init__`, which takes no arguments (`framework/openai/openai.py:644`, `framework/adk/adk.py:939`).
- `connect(session, agent, callback)`:
  1. `self._call_span = self._start_call_span(session, agent)`;
  2. `with self._call_span.opened(): await super().connect(session, agent, self._watched(callback))`;
  3. on any exception (cancellation included): `fail(repr(error))`, `end()`, `self._call_span = None`, re-raise. The adapters close what they opened before raising (`core/realtime/runner.py:65`).
- `_watched(callback)` returns a coroutine function that calls `self._call_span.fail(data.get("message") or "realtime session error")` for an `error` event, then awaits `callback(event_type, data)` for every event, unchanged.
- `disconnect()`: `try: await super().disconnect() finally:` end the span once and clear it. `disconnect` may run twice (`core/realtime/runner.py:98`); the span is ended once.
  - While `connect` is still running (`_connecting`), `disconnect` does not end the span: an adapter closes itself when its own connect fails (`framework/openai/openai.py:696`, `framework/adk/adk.py:999`), and that must not end the span before `connect` has marked it failed. The failed connect's handler fails and ends it.
- The span therefore covers the native session, not the pool's hooks, as a `run()` span covers `runner.run` and not the post-hooks (`core/runtime.py:537-541`).
- `BaseTrace` gets two non-abstract methods, `openai_realtime()` and `adk_realtime()`, each `-> type[RealtimeRunner] | None`, returning `None` (the `fetch_spans` precedent, `trace/base.py:71`). They return a class, because the pool builds the realtime runner with no arguments, once per call (`pipeline/realtime_pool.py:94`).
- `Trace` (`trace/trace.py`) delegates both, returning `None` when it has no instance, like its framework methods.

#### 3.2 The OpenTelemetry call span (`trace/otel.py`, new)

For the three providers whose backend exports every span on the OpenTelemetry tracer provider they install: logfire, openllmetry, cloudwatch. Imported only by those provider packages; each one's extra brings `opentelemetry` (`langfuse`, `logfire` and `traceloop-sdk` require it; `cloudwatch` lists it, `pyproject.toml:41-46`).

```python
class OTelRealtimeCallSpan(RealtimeCallSpan):
    def __init__(self, tracer: Tracer, name: str, attributes: Mapping[str, str]): ...
    def _tagged(self) -> AbstractContextManager[None]:  # provider session tagging around the start; default none
```

- `opened()`: inside `self._tagged()`, `span = tracer.start_span(name, attributes=attributes)`, then `with trace.use_span(span, end_on_exit=False): yield`. `use_span` records an exception raised in the block on the span and sets its status.
- `fail(message)`: `span.set_status(Status(StatusCode.ERROR, message))` when a span exists.
- `end()`: `span.end()` once.
- Verified by experiment: a span opened this way only around ADK's `connect`, and ended from another task in `disconnect`, is the parent of ADK's `invoke_agent` span, whose child is `execute_tool` (google-adk 2.8.0).

#### 3.3 Per provider

| Provider | Call span | Session tagging (as its `run()` span) | Runner classes |
| --- | --- | --- | --- |
| langfuse | `LangFuseRealtimeCallSpan` (`trace/langfuse/langfuse.py`): `opened()` enters `propagate_attributes(session_id=..., tags=["agentkernel"])` and `client.start_as_current_observation(name=..., as_type="span", end_on_exit=False)`, keeping the observation; `fail` → `observation.update(level="ERROR", status_message=...)`; `end` → `observation.end()`. Client: `get_client()`, the singleton `LangFuse.init` also uses (`trace/langfuse/langfuse.py:42`). | `propagate_attributes(session_id=...)` (`trace/langfuse/openai.py:36`) | `LangFuseOpenAIRealtimeRunner` in `langfuse/openai.py`, `LangFuseADKRealtimeRunner` in `langfuse/adk.py` |
| logfire | `OTelRealtimeCallSpan` on `trace.get_tracer("agentkernel.trace.logfire")` | attribute `session_id` (`trace/logfire/openai.py:30`); `_keep_session_id` keeps it from scrubbing | `LogfireOpenAIRealtimeRunner`, `LogfireADKRealtimeRunner` |
| openllmetry | `OpenLLMetryRealtimeCallSpan(OTelRealtimeCallSpan)` in `openllmetry.py`; `_tagged()` attaches a context, calls `Traceloop.set_association_properties({"session_id": ...})`, and detaches it on exit, so the property is in the context the span and its children start in and leaks to nothing else | association property `session_id` (`trace/openllmetry/openai.py:28`), stamped on span start by Traceloop's processor (`traceloop/sdk/tracing/tracing.py:407-409`) | `OpenLLMetryOpenAIRealtimeRunner`, `OpenLLMetryADKRealtimeRunner` |
| cloudwatch | `CloudWatchRealtimeCallSpan(OTelRealtimeCallSpan)` in `cloudwatch.py` on the provider's tracer name `agentkernel.trace.cloudwatch` (`:57`); `_tagged()` attaches `session.id` baggage, as `CloudWatch.span` does (`:91`) | attribute and baggage `session.id`, which `SessionSpanProcessor` stamps on child spans (`:36-46`) | `CloudWatchOpenAIRealtimeRunner`, `CloudWatchADKRealtimeRunner` |

- Span names: `SPAN_NAME = "Agent Kernel OpenAI realtime"` / `"Agent Kernel ADK realtime"`, beside the run spans' `"Agent Kernel OpenAI"` / `"Agent Kernel ADK"`.
- Each runner class is `class X(TracedRealtimeRunner, <Framework>RealtimeRunner)` with `SPAN_NAME` and a two-line `_start_call_span`. The text runner's `__init__` installs the instrumentor (for example `trace/langfuse/adk.py:24`); an app that passes its own text runner never builds it, so each provider's `openai_realtime()` / `adk_realtime()` installs it too, once, written as the text runner writes it with an `is_instrumented_by_opentelemetry` check. The runner reaches its provider's client the way `develop` does: `get_client()` (Langfuse) and `get_tracer("agentkernel.trace.cloudwatch")` (CloudWatch). CloudWatch's `session.id` baggage is set in one place, `SessionSpanProcessor.tagged`, for `CloudWatch.span` and the call span.
- Langfuse needs its own API: its default export filter drops a span that has no `gen_ai.*` attribute and does not come from its tracer (`langfuse/_client/span_filter.py:104-108`, langfuse 4.15.1).
- No Lambda flush: a realtime call never runs on Lambda (the pool runs in a long-lived runner process).
- Each provider's `openai_realtime()` / `adk_realtime()` imports and returns its class, lazily, as its framework methods do.

#### 3.4 `Module` selection (`framework/openai/openai.py:923-929`, `framework/adk/adk.py:1237-1243`)

```python
tracer = Trace.get() if AKConfig.get().trace.enabled else None
self.realtime_runner_cls = realtime_runner_cls or (tracer.openai_realtime() if tracer else None) or OpenAIRealtimeRunner
self.runner = runner if runner is not None else (tracer.openai() if tracer else OpenAIRunner())
```

- The class is picked on `trace.enabled` alone, as the traced runner is. The framework does not know the execution mode: the realtime class is attached unconditionally and only the pipeline, in realtime mode, ever builds it (`pipeline/agent_runner.py:429-431`), so a text-mode app never instantiates it.
- `Trace.get()` is called once per `Module`, inline as in every other framework module (it builds and initialises a provider each time, `trace/trace.py:28-36`).
- A class the app passes is used as is, as a `runner` the app passes is.
- A tracer that returns `None` (a bring-your-own tracer without the methods) leaves the untraced default.
- `core/module.py` is not changed.

### Consumer changes

| Consumer | Change |
| --- | --- |
| `core/runtime.py` | None. |
| `pipeline/realtime_pool.py` `RealtimeConnection` | Section 2. |
| `framework/openai/openai.py`, `framework/adk/adk.py` `Module.__init__` | Section 3.4. The realtime adapters themselves are unchanged. |
| `trace/<provider>/` | Two runner classes each, and a call-span class for langfuse, openllmetry, cloudwatch. |
| `pipeline/agent_runner.py`, `deployment/aws/containerized/akagentrunner.py` | None: both still call `RealtimeConnectionPool.dispatch`. |
| `integration/livekit/adapter.py`, `pipeline/response_handler.py` | None: no output changes. |
| `core/session/*` stores | None. Each receives the `Session` as from `Runtime.stream`. |

### Config changes

None. No `AKConfig` field, extra, factory branch or provider is added. `session.*` picks the store, `trace.enabled` / `trace.type` the tracer, `execution.mode` whether the realtime runner is traced. Existing YAML and `AK_*` variables are unchanged.

### Behavioural changes

1. A realtime call stores its session after each finished turn and once when it ends normally. With a durable store, a call's changes (owner, non-volatile cache, ADK's conversation) now survive the call. *Intentional (#885).*
2. The write runs on a worker thread, where `Runtime.stream` writes on its own loop. *Stated difference: the pool loop is shared by every call.*
3. A failed call, or a process that dies mid-call, stores nothing more: it loses at most the turn in progress. *Intentional: a text run loses at most one request, which the queue retries; a call is many turns and nothing retries them.*
4. With `trace.enabled` in realtime mode, each call opens one AK span named `Agent Kernel <Framework> realtime`, tagged with the session id; ADK's native spans become its children. *Intentional.*
5. `close()` waits for the store before it ends the run. A slow store delays that call's close by the write. *Accepted.*

**Non-changes:** `run()` / `stream()` results, hook order and session storage; session store data layouts and what each store writes (the volatile cache stays out); the realtime output sequence; the edge; adapters' `connect` / `append_audio` / `send_text` / `disconnect`; principal publication per input; text-mode tracing; `BaseTrace`'s abstract methods (bring-your-own tracers still construct).

## Error handling

| Failure | Result |
| --- | --- |
| The store raises (backend down, value not picklable) | Logged at `ERROR` with the traceback; the identity and volatile cache are still cleared; the close completes |
| The native session fails (`_fail`) or fails to start | No store |
| The tracer's `opened()` raises | `connect` fails as any connect failure does (`fail_to_connect`, one error chunk to the edge) |
| `connect` raises inside the span | The span is marked failed and ended; the error propagates unchanged |
| An `error` event during the call | The span is marked failed; the event reaches the pool unchanged |
| `trace.enabled` with a tracer lacking the realtime methods | `None`: the untraced runner is used |

Concurrency: the write runs on a worker thread from `asyncio.to_thread`, on the store instance `Runtime` already shares across consumer threads; built-in drivers serialise connects with a lock (shared-driver rule). Cost: one store write per call (one network call per durable key on redis, valkey, dynamodb), off the loop.

## Testing

New files:

- `tests/test_realtime_session_store.py`, with its own fakes and the real `asyncio.to_thread` (`tests/test_realtime_pool.py` runs it inline), over a recording store on the connection's `Runtime`:
  - a normal close stores once, the session itself, on a worker thread; a finished turn stores a copy off the loop, later changes stay out of it, writes land in turn order with the close write last, a halted turn stores nothing, a call that fails after a turn leaves that turn stored; a second close stores nothing more;
  - a post-hook's non-volatile cache write during the call is stored; the volatile cache is empty once the run ends;
  - the store is attempted when `disconnect` raises; a failing store is logged and the identity and volatile cache are still cleared;
  - none after a native error or a failed connect;
  - a slow store at one call's close does not block another call's audio;
  - durable round trip: a real `ValkeySessionStore` over a fake client; a second store instance (another pod) loads the owner and the non-volatile cache after the call.
- `tests/test_realtime_system_tools.py`: the real `create_schedule` in a live call on the real OpenAI SDK session (`ScriptedModel`, `tests/test_openai_realtime.py`) and ADK `run_live()` (a fake live model calling the tool, `tests/test_adk_realtime.py`), for a caller principal, no principal, and a principal changed between two inputs through `dispatch` on the real pool thread (the design's experiment).
- `tests/test_trace_realtime.py`:
  - `TracedRealtimeRunner` over a recording `RealtimeCallSpan` and a fake adapter: opened around `connect` (the adapter sees it active), ended once after two `disconnect`s, failed and ended and re-raised on a raising `connect` (including `CancelledError`), failed on an `error` event that still reaches the callback, `disconnect` without `connect` is safe, the MRO calls the framework runner's `__init__`;
  - `OTelRealtimeCallSpan` on a tracer from a local SDK `TracerProvider` with `InMemorySpanExporter` (never a global provider): name and attributes, a span started inside `opened()` and one started by a task created there both have the call span as parent, the call span is not current after the block, error status on `fail` and on an exception in the block, `end` idempotent, ended from another task;
  - `LangFuseRealtimeCallSpan` with a fake client and `propagate_attributes` patched: `end_on_exit=False`, the session id, `update(level="ERROR", ...)`, one `end()`;
  - `Module` selection: a dotted-path tracer stub returning recording classes; realtime mode gets the traced class on both modules, a passed class is kept, text mode keeps the traced class attached too (as the default realtime class is) and never builds an instance of it, a tracer returning `None` leaves the default, `Trace.get()` called once per module.
- Per-provider classes in the existing provider test files, which already stand up each provider: `tests/test_trace_cloudwatch.py` (the realtime runners subclass the framework runners; the call span carries `session.id`; a child span gets it through baggage), `tests/test_trace_logfire.py` (fake `logfire` module; runner classes and the `session_id` attribute), and the OpenLLMetry association property with `Traceloop.set_association_properties` patched in `tests/test_trace_realtime.py`.

Existing tests that change:

- `tests/test_realtime_pool.py` `TestRealtimePrincipal.test_closing_unpublishes_the_identity` (`:419`): unchanged.
- `tests/test_realtime_hooks.py`: the close tests (volatile cache cleared, also when `disconnect` raises) keep their assertions; the store-when-`disconnect`-raises case lives in `tests/test_realtime_session_store.py`.
- `tests/test_ecs_akagentrunner_realtime.py:175`: unchanged. Its `SimpleNamespace` agent supplies `_activate`, and a real `Session` and `InMemorySessionStore`, which the close stores.
- Not changed, re-run: `tests/test_realtime_edge_path.py`, `tests/test_openai_realtime.py`, `tests/test_adk_realtime.py`, `tests/test_livekit_edge_adapter.py`, `tests/test_runtime.py`, `tests/test_runtime_stream_events.py`, `tests/test_runtime_principal.py`, `tests/test_trace.py`, `tests/test_trace_langfuse_flush.py`.

Run: `cd ak-py && uv run pytest tests/test_realtime_session_store.py tests/test_realtime_system_tools.py tests/test_trace_realtime.py tests/test_realtime_pool.py tests/test_realtime_hooks.py tests/test_trace_cloudwatch.py tests/test_trace_logfire.py`, then `uv run pytest`, then `make lint-check`.

## Design requirements traced

| design.md requirement | Spec section |
| --- | --- |
| `Runtime` and identity publication unchanged | 1, 2.1 |
| Store once at a normal call end, the `Runtime.stream` rule | 2.2 |
| No store after a failure | 2.2 |
| Write off the shared loop; failed store logged | 2.2, Error handling |
| No lock; volatile cache per call; principal and `ToolContext` kept | 2.3 |
| System tool acting as the caller inside a call: permanent test | Testing |
| Traced realtime runner picked by the `Module`; app's class kept | 3.4 |
| Optional `BaseTrace` methods; bring-your-own tracers unaffected | 3.1 |
| One span from connect to disconnect; session tagged as the provider's `run()` span; native ADK spans as children; error marking | 3.1, 3.2, 3.3 |
| Hooks outside the span | 3.1 |
| Span through the provider's API where its export filter needs it (Langfuse) | 3.3 |
| No new config | Config changes |
| Docs and stale docstrings | Plan, docs iteration |
