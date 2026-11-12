# #928: Realtime calls follow the AK run lifecycle: session, context and tracing

A realtime call should use AK's main building blocks (`Runtime`, `Session`, hooks, tool context, tracing) the way
every other mode does, without copying every AK capability onto a live call. Today the pool repeats `Runtime`'s start
and end steps itself, a call never stores its session, and a call gets no AK trace span.
This change gives the scoping and end steps back to `Runtime`, leaves identity publication as #603 designed it, stores the session, and traces a call through a traced realtime
runner, as text runs are traced. What already works on a call is kept. Capabilities that do not fit a live call are
left out and documented, not forced.

## Scope: part 2 of #885

- #885 aligns realtime with the rest of AK. Part 1, #927 (`feature/927-realtime-hooks`), did it for hooks: `Runtime` owns the hook loops and the pool calls them.
- The test for every point here: does a realtime call need it in practice? If it already works, it is kept. If it does not fit a live call, it is documented and left out.
- The text of #928 is the starting list, not the spec.
- #927 left three points to this part: a lock per turn, storing the session after a turn, clearing the volatile cache per turn (`docs/specs/927-realtime-hooks/design.md:85`, `:128`).

## Each run step: other modes, a call today, this change

| Step | `run()` / `stream()` | A realtime call today | This change |
| --- | --- | --- | --- |
| Pick agent and session | `ChatService` → `AgentService` (`core/service.py:109`) | Same, through `prepare_agent_handler` (`pipeline/realtime_pool.py:713`) | None |
| Session lock | `Runtime` (`core/runtime.py:514`) | None | None: a stated departure |
| Publish the principal, record the owner | `Runtime._publish` (`core/runtime.py:516`) | The pool calls `Runtime._publish` (`pipeline/realtime_pool.py:112`), as #603 section 8.4 specifies | None: kept (below) |
| `Session.current()`, `Agent.current()` | `Runtime` (`core/base.py:121`, `core/runtime.py:517`) | The pool sets the context variable and calls the private `Agent._activate` (`pipeline/realtime_pool.py:138-140`, `:239-241`) | A public `Runtime` method (`activate`) |
| Pre-hooks and post-hooks | `Runtime` | `Runtime`'s public hook loops (#927) | None |
| `ToolContext` | The adapter, per run (`framework/openai/openai.py:234`) | The pool, once per call (`pipeline/realtime_pool.py:137`) | None: works, kept |
| Store the session | `Runtime`, after a successful run (`core/runtime.py:546`, `:627`) | Never | Stored once, when the call ends normally (the `Runtime.stream` rule) |
| Unpublish, clear the volatile cache | `Runtime`, in `finally` (`core/runtime.py:549-550`, `:641-642`) | The pool calls the private `Session._unpublish_run` and `KeyValueCache._clear_all` (`pipeline/realtime_pool.py:455`, `:458`) | A public `Runtime` method (`end_run`) |
| `framework_context` | The adapter (`framework/openai/openai.py:245-251`) | Not carried (`core/realtime/runner.py:19`) | None: not needed on a call (below) |
| Tracing | A traced runner per framework, picked by the `Module` (`framework/openai/openai.py:925-929`) | ADK: native spans. OpenAI: none. The realtime runner class is never traced (`:923`) | A traced realtime runner per framework, picked by the `Module` |

## What already works, and is kept

Verified on the code, by the existing tests named here, and by running an experiment (last point).

- Acting user on a call.
  - Each input's principal is published on the session, on the pool loop, before that input reaches the model. Only a changed principal is republished, because every audio chunk is an input (`pipeline/realtime_pool.py:96-112`, called from `dispatch` at `:717`).
  - The agent is the actor and the session owner is recorded, by the same step a text run uses (`core/runtime.py:428-450`). `close()` unpublishes it (`pipeline/realtime_pool.py:454-455`).
  - Tests: `TestRealtimePrincipal`, `TestDispatchPrincipal` in `tests/test_realtime_pool.py`.
- Context inside native tools and hooks.
  - `ToolContext`, `Session.current()` and `Agent.current()` are set around `adapter.connect`, and the SDK's tool tasks inherit them (`pipeline/realtime_pool.py:135-144`). Tests with the real SDKs: `tests/test_openai_realtime.py:835`, `tests/test_adk_realtime.py:718`.
  - Hooks get `Session.current()` and `Agent.current()` (#927, `pipeline/realtime_pool.py:233-244`).
  - After a native handoff, `Agent.current()` and the principal's actor stay the call's root agent. A text run does the same: the SDK hands off inside one `Runtime.run` (`core/runtime.py:517`).
- Hooks on a call (#927).
- Volatile cache: cleared once, when the call closes, also when the native session fails to close (#927, `pipeline/realtime_pool.py:451-458`).
- System tools that act as the caller work inside a call, on both adapters. Checked with the schedule tools.
  - They read `Session.current().get_principal()` and refuse an anonymous run (`schedule/tools.py:72-81`, `:186-188`).
  - Experiment (scratch, not committed; the spec makes it a test): the real `create_schedule` system tool, attached by the real attach path, run by the real OpenAI SDK realtime session (scripted model, as in `tests/test_openai_realtime.py`) and by ADK `run_live()` (fake live model, as in `tests/test_adk_realtime.py`), through `RealtimeConnection`:
    - Caller principal (`realtime:livekit`): the task is created, owned by the caller, with the call's session id.
    - No principal: the tool returns `{"error": "scheduling requires an authenticated principal"}`.
    - Through the real pool thread and `dispatch()`, with the principal changed between two inputs: each tool call acts as the principal of the input before it.

## Motivation

- Two owners of the run lifecycle.
  - The pool repeats `Runtime`'s scoping and end steps itself, through `Agent._activate`, the `Session.current_session` variable, `Session._unpublish_run` and `KeyValueCache._clear_all` (table above).
  - So a change to how a run is scoped or ended has to be made in two places. #927 removed this for hooks; these steps are still duplicated.
  - Identity publication is not part of this: the pool publishes each input's principal through `Runtime._publish` on purpose (#603, section 8.4), `Session` documents that exception (`core/base.py:270-272`), and the access gate is planned to slot into `_publish` (`core/runtime.py:432-434`). Making it public would add a documented way to publish any principal on a session, which #603's unforgeable-identity design avoids.
- A call never stores its session.
  - A call works on the session the store handed out when it opened (`pipeline/realtime_pool.py:713`, loaded at `core/service.py:109`).
    - `in_memory`: that is the store's own object, so nothing is lost while the process lives.
    - A durable store (redis, valkey, dynamodb, cosmosdb, firestore): it is a copy, and everything the call changed is dropped when it ends. That includes the owner recorded at the first input (`core/runtime.py:449`), what hooks keep in the non-volatile cache, and ADK's live conversation, which ADK appends to the `GoogleADKSession` kept on the AK session (`framework/adk/adk.py:296`, `:985-986`).
  - Where it shows: the native session fails and the next input reconnects on another runner process; or the caller follows up by text after the call. Both start from the session as it was before the call.
  - Native fact: OpenAI keeps the conversation inside its `RealtimeSession`; the adapter puts nothing on the AK session.

## Requirements

### Principle

- A call is one run, as a streamed run is one run in `Runtime.stream`: start-of-run and end-of-run steps happen once per call, the store included.
- Consistency with the rest of AK is kept unless it causes a critical issue; then the departure is discussed and stated.
- Identity publication is not changed: it stays as #603 designed it, so the access gate keeps one place to slot into.
- Each departure from a text run is stated with its reason.

### `Runtime` owns the call's lifecycle

- `Runtime` gets public methods for the lifecycle steps of a run it does not drive, as #927 did for the hook loops:
  - make the session and the agent current, without the lock;
  - end the run (unpublish, clear the volatile cache).
- `run()` and `stream()` use the same methods, so each step has one owner. Their behaviour does not change.
- The pool calls these methods instead of `Agent._activate`, `Session.current_session`, `Session._unpublish_run` and `KeyValueCache._clear_all`.
- Identity publication stays as #603 specifies: the pool calls `Runtime._publish` per input, and `Session._publish_run`'s docstring is unchanged.

### Session store

- The call stores its session once, when it ends normally (the edge ended it, idle eviction, shutdown), through the runtime's session store (`runtime.sessions().store(session)`): the `Runtime.stream` rule, one store at the end of a stream that ended normally (`core/runtime.py:627`). A call is a two-sided stream.
- No store after a failure (`_fail`: a native error, a `StreamHalt`, a raising post-hook; a failed connect), as `Runtime.stream` does not store a halted run (`core/runtime.py:629`).
- The store runs after the adapter has disconnected (ADK flushes its session service there, `framework/adk/adk.py:1125-1126`) and before the run ends (`end_run`), the order `Runtime.stream` uses.
- One stated difference: the write runs on a worker thread, not on the loop.
  - `Runtime.stream` writes on its own loop, which nothing else shares. The pool's loop serves every call in the process (`pipeline/realtime_pool.py:461-465`), and a store is synchronous network I/O, one write per session key (`core/session/redis.py:100-101`, `core/session/dynamodb.py:104-106`). On the loop, each call's end would stall every other call's audio, which the edge buffers only `playback_lead_ms` ahead, 50 ms by default (`core/config.py:681-682`).
  - The store call itself is unchanged, and the stored object is the session itself, as in `Runtime.stream`: no copy, no new API.
  - Accepted, narrow risk: an input chunk whose hooks are still running when the call closes could change the session while the thread writes it. The native session and pacing have already stopped by then.
- A failed store is logged and the call still ends.
- What this gives up, consistently with a stream: a process crash or a native-session failure mid-call loses that call's changes on a durable store; the next connection starts from the session as it was before the call.
- Against another run on the same session id, the last store wins (no lock, below). This is already the case between two processes.
- Existing apps: a call on a durable store starts storing its session. Intended (#885), not opt-in.

### Session lock: a stated departure

- Not taken, as today (`pipeline/realtime_pool.py:135-136`). Reasons:
  - AK sees the end of a model turn (`done`) but not its start, and the two directions overlap: the caller's next audio goes through the input hooks while the model's reply is still being paced (`_process_audio`, `:353`, and `_pacing_loop`, `:282`, run independently). No lock span covers one turn and only that turn.
  - Holding it for the whole call would block every other run of the session for minutes (the pool's own reason, `:136`).
  - `Session._lock` is an `asyncio.Lock` (`core/base.py:91`), and the pool loop is not the loop of any other run. Across loops it does not serialise: once bound to one loop, a waiting acquire from another loop raises `RuntimeError` (checked on Python 3.13).

### Volatile cache: per call, kept

- Cleared once, when the call ends (#927 already does this). Not per turn. Reasons:
  - It is the `Runtime.stream` rule: one clear when the stream ends, however many messages it carried (`core/runtime.py:642`).
  - A clear at the model's `done` would wipe an input hook's state for the caller's next words, which may already be arriving (the overlap above).
  - A hook that wants per-turn state resets its own keys at `MessageEnd`.
- The published principal is under a reserved key; neither choice touches it while the call is open (`KeyValueCache.clear` keeps reserved keys, `core/util/key_value_cache.py:81-85`).

### Acting user, context and system tools: kept

- No behaviour change to principal publication, `ToolContext`, `Session.current()` or `Agent.current()` on a call.
- `ToolContext.requests` stays empty on a call: a call has no request list, and audio has no request at all. A stated difference.
- A permanent test that a system tool acting as the caller works inside a live call, on both adapters, for a caller, an anonymous input, and a principal that changes between inputs (the experiment above, with `create_schedule`).

### Tracing: AK's layer on a call

What a call gets today, measured (scratch experiment: each SDK's spans collected during a live call that runs one tool):

- ADK is traced natively. One `invoke_agent <agent>` span lasts the whole call and carries the AK session id as `gen_ai.conversation.id`; each tool call is an `execute_tool <tool>` child (`google/adk/agents/base_agent.py:380`, `google/adk/flows/llm_flows/functions.py:1021`, google-adk 2.8.0). Both carry `gen_ai.*` attributes, so even Langfuse's default export filter keeps them (`langfuse/_client/span_filter.py:104-108`, langfuse 4.15.1).
- OpenAI is not traced at all. A call that ran a tool produced no SDK trace, no SDK span and no OpenTelemetry span; a control span in the same test arrived. The SDK's realtime code creates no spans (none under `agents/realtime/`, unlike `agents/run.py` and `agents/run_internal/tool_execution.py`, openai-agents 0.20.0). Its only tracing is OpenAI's own, on OpenAI's servers (the `tracing` model setting, `agents/realtime/config.py:244`).
- So the gap is realtime-only. A text run gets two layers: AK's traced runner adds one span with the session id (`trace/langfuse/openai.py:36-38`), and the instrumentor copies the SDK's spans (`docs/docs/advanced/traceability.md:480`, `:565`). A call has neither on OpenAI, and only the SDK's on ADK.

Requirements:

- When `trace.enabled` and `execution.mode` is `realtime`, the `Module` picks a traced realtime runner from the configured tracer, the way it picks the traced runner (`framework/openai/openai.py:925-929`, `framework/adk/adk.py:1239-1241`). Only realtime mode ever builds a realtime runner, so text-mode apps are unchanged. A `realtime_runner_cls` the app passes is used as is, as a `runner` the app passes is.
- `BaseTrace` gets one optional method per realtime framework (OpenAI, ADK). Not abstract: by default it returns nothing and the untraced class is used, so bring-your-own tracers keep working (the `fetch_spans` precedent, `trace/base.py:71`).
- A traced realtime runner opens one span when `connect` starts and ends it in `disconnect`.
  - It tags the session id the way that provider's `run()` span does.
  - The native session's tasks start inside it, so ADK's native spans become its children.
  - A failed connect, or a native error reported during the call, marks it as an error.
- Hooks run outside it, as post-hooks run outside the `run()` span (`Runtime` calls them after `runner.run` returns, `core/runtime.py:537-541`).
- Built-ins: langfuse, openllmetry, logfire, cloudwatch, each for OpenAI and ADK, next to their existing traced runners.
- Each provider creates the span in a way its backend exports:
  - Langfuse through its own client, because its export filter drops a span that has no `gen_ai.*` attribute and does not come from its own tracer (`langfuse/_client/span_filter.py:104-108`).
  - Logfire, OpenLLMetry and CloudWatch as an OpenTelemetry span on the tracer provider each one installs, which they export in full. Logfire's own span object can only be used inside one block (its start and end are private), and a call's span outlives the task that opens it.
- OpenAI's missing model and tool spans are an SDK limit: documented, not rebuilt by AK.

### Component structure

- No new pool class. `RealtimeConnection` calls `Runtime`'s public lifecycle methods and the session store, where it calls the hook loops today (house pattern 3). No new session or store API.
- No change to adapter behaviour. Each `Module` picks the traced realtime runner where it picks the traced runner.
- Tracing: two optional methods on `BaseTrace`, delegated by `Trace`; one shared base for the traced realtime runners (the open-at-connect, end-at-disconnect rule, written once); traced realtime runner classes in each built-in provider's package.

### Configuration

- No new `AKConfig` fields and no new extra. `session.*` already picks the store; `trace.enabled` and `trace.type` already pick the tracer.
- Existing YAML and `AK_*` env vars work unchanged.

### Documentation

- Correct "the AK session is not saved when a call ends" (it is now stored at the end of a call that ended normally): `docs/docs/integrations/livekit.md:160`, `docs/docs/architecture/realtime-internals.md:52`, `.agents/skills/ak-dev-architecture/SKILL.md:638`.
- Correct the stale `Agent.__init__` docstring: "realtime runner class for WebSocket connections" (`core/base.py:610`).
- `docs/docs/integrations/hooks.md`: per-turn state in the volatile cache is reset by the hook itself.
- `docs/docs/advanced/traceability.md`: a realtime section: the call span per provider, ADK's native spans, OpenAI's SDK limit and its own server-side tracing.
- `docs/docs/integrations/livekit.md`: the scheduling limit below.

## Not in this change

Each was checked against a realtime call in practice; none is forced onto it.

- A turn log shipped by AK. #928 does not define one. After #927 a post-hook sees every per-turn event (`InputTranscript`, `TextDelta`, `AgentChanged`, `Interrupt`, `MessageEnd`), and with this change what it keeps in the non-volatile cache is stored when the call ends.
- Scheduled occurrences in a realtime deployment. Creating a schedule during a call works (above). An occurrence, though, is a chat request with no caller listening, and a realtime runner sends it to the call pool (`pipeline/agent_runner.py:433-439`), never through `ChatService`, so it is not recorded (`core/chat_service.py:576`). With no live call it opens a native session whose output nobody reads; with a live call on the same session it is sent into the call as text and briefly replaces the call's reply route (`pipeline/realtime_pool.py:702-716`). This is documented as a limit, not fixed: an occurrence can still work when the schedule provider delivers to a text-mode deployment's queue.
- `framework_context` on a call. The native tools on a call get no context object (the OpenAI adapter passes no `context` and rejects it as a run option, `framework/openai/openai.py:641`); they reach the AK session through `ToolContext`. It would matter only for tool functions shared between a text agent and a voice agent, and would change both adapters (both natives could take it: `agents/realtime/runner.py:48-49`; ADK session state, `framework/adk/adk.py:993`).
- AK-built model and tool spans for OpenAI calls (an SDK limit, above).
- `ToolContext` built by each adapter instead of the pool. The pool builds it today (`pipeline/realtime_pool.py:137`); it works on both adapters, so it is kept.
- Native tool calls reported as AK events (`ToolCallStart` / `ToolCallResult`), as delta-mode runners emit them. It changes both adapters and what the edge receives.
- Restoring a native conversation after a reconnect or a restart. OpenAI keeps its history inside the native session only (native fact).
- A lock that serialises a call against other runs of the same session.
- A session span for streamed text runs (SSE and WebSocket delta modes). After this change a call has one and a streamed run still does not; covering `stream()` is its own change across every traced runner.

## Decisions taken in review

1. Store the session once, when the call ends normally, as `Runtime.stream` does (first decided as per turn plus call end; changed for consistency: a call is a two-sided stream). The write runs off the shared loop.
2. `framework_context` is not carried on a call.
3. Tracing is in this change: AK's layer through traced realtime runners; OpenAI's model and tool spans stay an SDK limit.
4. Scheduled occurrences, a turn log, native tool events and a lock stay out (above).
