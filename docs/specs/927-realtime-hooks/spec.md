# #927: Pre-hooks and post-hooks on realtime calls — Implementation Spec

This spec details [design.md](design.md). A realtime call runs the existing hooks the way a delta-mode run does: typed
caller text through `PreHook.on_run`, every model output event through `PostHook.on_stream_event`, and caller audio
through one new optional method, `PreHook.on_stream_input`. `Runtime` owns the hook loops (one owner of hook order);
`RealtimeConnection` calls them. No new class, no config, no adapter change.

Line numbers cite the branch at `10e2d0579` and were read, not remembered.

## Design

### 1. `PreHook.on_stream_input` (`core/hooks.py`)

```python
class PreHook(ABC):
    async def on_stream_input(
        self, session: "Session", agent: "Agent", request: AgentRequestVoice
    ) -> AgentRequestVoice | list[AgentRequestVoice | AgentRequestText] | None:
        """Called for every caller audio chunk of a realtime call, before it reaches the model. Default: pass it on."""
        return request
```

- Non-abstract, default returns `request`: every existing `PreHook` (including the three system pre-hooks) is unchanged and needs only `on_run` (`core/hooks.py:42`).
- Return rules, mirroring `on_stream_event` (`core/hooks.py:94`):
  - `None`: the chunk is dropped; later hooks and the model never see it.
  - One `AgentRequestVoice`: passed to the next hook. Any other single type raises `TypeError` naming the hook ("return a list to emit a different type"), as `Runtime.stream` does at `core/runtime.py:531-535`.
  - A list: emitted as-is and **ends the chain for that chunk**. Items must be `AgentRequestVoice` (go to the model) or `AgentRequestText` (go to the typed-text path, section 3.3); any other item raises `TypeError` naming the hook.
- `session` has `Session.current()` set and `agent` is `Agent.current()` (section 3.1). One hook instance serves every call: per-call state goes in `session.get_volatile_cache()`, not on `self` (same rule as `core/hooks.py:94`).
- The audio is base64 PCM16 at the edge rate, `EDGE_SAMPLE_RATE` = 24000 (`core/realtime/pcm.py:12`). The pool converts to the model's rate after the hooks.
- Imports: `AgentRequestText`, `AgentRequestVoice` join the existing `from .model import ...`.

### 2. Runtime hook API (`core/runtime.py`)

One place owns hook order and hook-return checks for every mode. Three public methods; `run()` and `stream()` behave as before.

```python
async def run_pre_hooks(self, agent, session, requests) -> list[AgentRequest] | AgentReply: ...
async def run_stream_input_hooks(self, agent, session, request: AgentRequestVoice) -> tuple[list[AgentRequestVoice], list[AgentRequestText]]: ...
async def run_stream_event_hooks(self, agent, session, requests, event: StreamEvent) -> list[StreamEvent]: ...
```

- `run_pre_hooks` is `_prepare_requests` (`core/runtime.py:226`) renamed and made public; its body is unchanged. Its two call sites (`:433`, `:494`) change. No other reference exists in `src/` or `tests/` (grep).
  - Order: `agent.pre_hooks + _get_system_pre_hooks()` (`:242`). Return validation is unchanged, including the tuple at `:253`, which does not list `AgentRequestVoice`; the realtime text path only passes it text.
- `run_stream_input_hooks` runs the same order, calls `on_stream_input` per hook, applies the return rules of section 1, and returns `(voice, text)`: the audio for the model and the text items hooks produced. `([], [])` when a hook drops the chunk.
- `run_stream_event_hooks` runs `_get_system_post_hooks() + agent.post_hooks` (`:515`) for one event and returns the events to emit (empty when dropped).
  - The hook loop of `stream()` (`:521-536`: `None` drops, a list ends the chain, a different `type` raises `TypeError`, `emitted = [ev]` when every hook passes) moves into a private `_run_event_chain(post_hooks, session, requests, agent, event)` returning `(emitted, event_after_rewrites, last_hook)`.
  - `stream()` calls it and keeps its RunPaused check (`:538-539`, `_warn_pause_dropped`) using the returned event and `last_hook`, because that call reads the hook the loop ended on. `last_hook` is `None` for an empty hook list, which `stream()` never has.
  - `run_stream_event_hooks` calls the same private method and returns `emitted`.
- None of the three takes the session lock, publishes a principal, stores the session or clears the volatile cache; callers own that (`run()`/`stream()` as today, the realtime connection as in section 3).
- Exceptions propagate, `StreamHalt` included.

### 3. `RealtimeConnection` (`pipeline/realtime_pool.py`)

No new class and no module-level function. New members are methods and two instance attributes of `RealtimeConnection`:

```python
self._turn_message_id: str | None = None   # message_id of the turn's last output event, for MessageEnd
self._last_turn: list[AgentRequest] = []   # the last text turn sent to the model; the `requests` argument post-hooks receive
self._input_failure_logged = False         # first audio-hook failure logged at ERROR, later ones at DEBUG
```

#### 3.1 Hook context

```python
@contextmanager
def _hook_context(self) -> Iterator[None]:
    """Session.current() and Agent.current() around a hook call."""
```

- Sets `Session.current_session` (the `ContextVar`, `core/base.py:74`) and enters `self.agent._activate()` (`core/base.py:724`), and resets both on exit.
- Needed because `_connect` sets them only around `adapter.connect` and resets them (`pipeline/realtime_pool.py:127-133`) before it creates the pacing task (`:140`), and an input coroutine scheduled through `run_coroutine_threadsafe` runs in the loop thread's context. So the pacing task and every input coroutine start without a session or agent.
- The session lock is not taken (a call is one long session, `:124-125`).

#### 3.2 Output path

```python
async def _emit_event(self, event: StreamEvent) -> list[StreamEvent]:
    """Run the event through the post-hooks, emit each resulting event as a chunk, return what was emitted."""
```

- Hook errors: `StreamHalt` is re-raised; any other exception is logged with its traceback (`ERROR`) and raised as `StreamHalt("Realtime output hook failed")` from it. The reason of a `StreamHalt` reaches the edge verbatim (`core/hooks.py:20`, `:34`), so a hook author's own `StreamHalt(reason)` is shown and an unexpected exception is not leaked.
- Each emitted event becomes `StreamChunk(delta=event.content if TextDelta else None, event=event)`, the shape `Runtime.stream` yields (`core/runtime.py:544`) and the shape `_pacing_loop` already builds. It then goes to `_emit` unchanged.
- `_pacing_loop` (`:220`) changes as follows:
  - `transcript_delta`, `input_transcript`, `interrupt`, `agent_changed`: build the same event as now (`:229`, `:232`, `:238`, `:241`) and call `_emit_event` instead of `_emit`.
  - `audio_delta`: after the resample (`:251`), build `AudioDelta`, call `_emit_event`, and pace by the audio actually emitted:
    - `emitted_ms` = the sum over emitted `AudioDelta` of `(len(pcm16_bytes) / 2) / (EDGE_SAMPLE_RATE / 1000)`.
    - When the emitted list is exactly the original event, the byte length is `len(pcm16)` (no second decode); otherwise the content is decoded.
    - `audio_played_ms += emitted_ms`; the sleep rule (`:258-261`) is unchanged. A dropped chunk adds no time and sleeps nothing extra.
  - `done`: build `MessageEnd(message_id=self._turn_message_id or uuid4().hex)`, call `_emit_event`, set `_turn_message_id = None`, then emit `StreamChunk(done=True)` as now (`:236`).
  - `_turn_message_id` is set from each dequeued `audio_delta` / `transcript_delta` whose `message_id` is non-empty. It is the id of the **last** output event of the turn, not a turn id: ADK gives every event its own id (`framework/adk/adk.py:1060-1069`, `event.id`), OpenAI uses the item id (`framework/openai/openai.py:756`, `:777`). Realtime sends no `MessageStart` (the native session reports pieces, not boundaries); `MessageEnd` marks the turn end.
  - `except StreamHalt as halt:` is added before the existing `except Exception` (`:265`): `await self._fail(halt.reason)` then `return`. Other exceptions keep today's handling (logged, loop continues).
- `done` is not an event to hooks, as in `Runtime.stream`; the `done` chunk follows the hooks' output for `MessageEnd`.
- Control events and `_interrupt` (`:174`) are unchanged: audio and transcript deltas queued behind a barge-in are still dropped before the hooks see them, and the `Interrupt` event reaches the hooks in order.
- `_queued_audio` (`:71`, `:155`, `:247`) is unchanged: it counts audio queued before the hooks. A hook that holds audio does not count as playing audio for a barge-in; the model's own `interrupt` still reaches the hooks.

#### 3.3 Input path

- `append_audio` (`:282`) and `send_text` (`:289`) keep their names and their thread-safe, bounded-blocking contract (`_dispatch_send`, `:294`, bounded by `_SEND_TIMEOUT_SECONDS`, `:33`) and now take the request object, so a hook sees the `name` and `mime_type` the edge set:

```python
def append_audio(self, request: AgentRequestVoice) -> None: ...   # was (audio_data: str)
def send_text(self, request: AgentRequestText) -> None: ...       # was (text: str)
```

- `dispatch` (`:595-599`) passes the request (`conn.append_audio(request)`, `conn.send_text(request)`). Requests of other types are ignored as today.
- Each schedules one coroutine on the pool loop, so the existing one-message-at-a-time ordering holds: the consumer thread blocks until the item has been processed, and the input queue already orders a session's messages (`group_id` = session id).
- Audio (`_process_audio(request)`):
  1. `voice, text = await runtime.run_stream_input_hooks(agent, session, request)` inside `_hook_context`.
  2. Each `voice` item: resample `request.audio_data` from `EDGE_SAMPLE_RATE` to `adapter.input_sample_rate` (as `:285` does today, now on the pool loop) and `await adapter.append_audio(...)`.
  3. Each `text` item: the typed-text path below, as if it had arrived typed.
  4. A raising audio hook: the chunk is dropped; the first failure of a connection is logged at `ERROR` with the traceback, later ones at `DEBUG` (`_input_failure_logged`), so a persistently failing hook does not flood the log at the chunk rate.
- Typed text (`_process_text(request)`):
  1. `result = await runtime.run_pre_hooks(agent, session, [request])` inside `_hook_context`; one typed item is one turn.
  2. `result` is an `AgentReply`: nothing is sent to the model; `_emit(StreamChunk(error=str(result), done=True))`, the chunk `Runtime.stream` yields for a pre-hook halt (`core/runtime.py:499`). The call continues.
  3. `result` is a list: `self._last_turn = result`; the `AgentRequestText` items' prompts are joined with `"\n"` and sent once with `await adapter.send_text(...)`. Non-text items (file, image, any) are dropped with a `DEBUG` line, since the native session takes text and audio only. Nothing is sent when no text is left.
  4. An exception from a pre-hook: logged with its traceback, `_emit(StreamChunk(error="Your message could not be processed.", done=True))`; the call continues.
- One text item per turn means a single dispatched message holding several text requests makes several turns, as it does today (`send_text` per request).

#### 3.4 `_fail` from the pacing task (`:192-205`)

- `_fail` cancels `self._pacing_task` (`:196-198`). Called from the pacing loop (the new `StreamHalt` branch) that would cancel the running task and could drop the error chunk it is about to send.
- Change: cancel only when `self._pacing_task is not asyncio.current_task()` (the pattern `_cancel_and_wait` uses, `core/realtime/runner.py:30`); the pacing loop returns right after `_fail`. `close()` (`:342-344`) still cancels the task from the close task.

#### 3.5 Volatile cache at call end (`close`, `:330`)

- After `await self.adapter.disconnect()` and the existing `_unpublish_run()` (`:346-347`), `close()` clears the session's volatile cache (`session.get_volatile_cache()._clear_all()`, the call `Runtime` makes at `core/runtime.py:464`). Hook state kept there (section 1) ends with the call.
- The cache is not cleared per turn (non-goal: session part of #885).

#### 3.6 Startup warning (`RealtimeConnectionPool.initialize`, `:364`)

```python
def _warn_unchecked_audio(self) -> None:  # on RealtimeConnectionPool
    """One WARNING per registered realtime agent when guardrail.input.enabled is on."""
```

- Called from `initialize()` right after the pool is created (inside the lock, once per process). For each agent in `Runtime.current().agents()` whose `realtime_runner_cls` is set and when `AKConfig.get().guardrail.input.enabled` (`_GuardrailParamConfig.enabled`, `core/config.py:480`) is true, one `WARNING`: the input guardrail checks typed text only; caller audio reaches the model unchecked.
- Not warned (Non-goals in the design): `guardrail.output.enabled`, a post-hook that overrides only `on_run`.

### Consumer changes

| Consumer | Change |
| --- | --- |
| `pipeline/agent_runner.py:439`, `deployment/aws/containerized/akagentrunner.py:329` | None. Both call `RealtimeConnectionPool.dispatch`. |
| `framework/openai/openai.py`, `framework/adk/adk.py` | None. They still receive `append_audio(str)` / `send_text(str)` on the adapter. |
| `integration/livekit/adapter.py` (`deliver_chunk`, `:424`) | None. `message_end` is not handled and falls through (it only triggers `_catch_up_speaker`, which is a no-op unless a speaker is pending). |
| `pipeline/response_handler.py` realtime delivery (`:65`) | None. It forwards the chunk to the edge. |
| `core/runtime.py` `run()` / `stream()` | Call `run_pre_hooks`; `stream()` calls `_run_event_chain`. Behaviour identical (tests in `test_runtime*.py` unchanged). |

### Config changes

No config changes. No `AKConfig` field, extra, factory or provider is added. The feature is enabled by registering a hook; `guardrail.*` is read only for the warning. Existing YAML and `AK_*` variables are unchanged.

### Behavioural changes

1. Agent pre-hooks and the system pre-hooks (input guardrail, multimodal, sandbox) run on every typed text turn of a realtime call. Before, none ran. *Intentional (#885).*
2. Agent and system post-hooks' `on_stream_event` run on every output event of a call. *Intentional.*
3. The edge receives a `MessageEnd` event before each `done` chunk, on every call, including calls with no hooks. Existing assertions on the output sequence change (Testing). *Intentional: hold-and-release needs a turn end.*
4. A blocked typed turn sends `StreamChunk(error=..., done=True)` to the edge. On LiveKit this clears the playing audio (`deliver_chunk`, `integration/livekit/adapter.py:430-434`). *Accepted: it is the existing terminal-error chunk.*
5. Caller audio is resampled to the model's rate on the pool loop instead of on the consumer thread. *Accepted: small CPU cost at the chunk rate; hooks need the loop.*
6. Pacing is computed from the audio emitted after the hooks. With no hooks the figure is identical.
7. A raising post-hook, or `StreamHalt`, ends the call through `_fail`; `_fail` no longer cancels the pacing task when called from it.
8. `close()` clears the session's volatile cache.
9. A startup `WARNING` per realtime agent when `guardrail.input.enabled`.
10. `RealtimeConnection.append_audio` / `send_text` take request objects.

**Non-changes:** adapters and their `append_audio(str)` / `send_text(str)`; queue message format (`message_end` is already a member of the `StreamEvent` union, `core/event.py:58`); hook order; `Runtime.run()` / `stream()` results; tools, principal publication, the session lock (not held) and session storage (not stored); the pool's reconnect back-off, eviction and shutdown.

### Decisions taken for the design's open questions

These were open in `design.md`; this spec assumes the recommendation. Reviewers confirm or change them, which changes `design.md` first.

1. Method name: `on_stream_input`.
2. `StreamHalt` in realtime ends the call (`_fail`).
3. System pre-hooks run in full on typed text, through the shared loop.
4. A raising audio hook drops the chunk; a raising or halting text hook sends one error chunk and the call continues.
5. The volatile cache is cleared at call close.
6. Not opt-in: hooks start running on existing apps.
7. `on_stream_input` has its own return validation; the tuple at `core/runtime.py:253` is unchanged.
8. `MessageEnd.message_id`: the last output event's id, else a fresh one; no `MessageStart`.
9. Held audio does not count for barge-in (`_queued_audio` unchanged).

## Error handling

| Failure | Result |
| --- | --- |
| Pre-hook returns an `AgentReply` for typed text | No send; error chunk with the reply text; call continues |
| Pre-hook raises on typed text | Logged; error chunk `"Your message could not be processed."`; call continues |
| `on_stream_input` raises | Chunk dropped; first one per connection at `ERROR`, then `DEBUG`; call continues |
| `on_stream_input` returns a wrong type | `TypeError` naming the hook, handled as a raise (chunk dropped) |
| Post-hook raises `StreamHalt(reason)` | `_fail(reason)`: one error chunk, connection closed, next input reconnects |
| Post-hook raises any other exception, or returns a different `type` for one event | Logged with traceback; `_fail("Realtime output hook failed")` |
| Hook slower than the budget | No time limit; a slow input hook can exceed `_SEND_TIMEOUT_SECONDS` (10 s): the wait gives up and logs, the item is still processed afterwards (existing `_dispatch_send` behaviour) |
| No hooks registered, guardrails off | Native path; only the `MessageEnd` of Behavioural change 3 differs |

Concurrency: hooks run on the pool's single event loop; hook instances are shared across calls, so per-call state lives in the session's volatile cache. Cost: per audio chunk, one await per input hook (agent hooks plus three system pre-hooks) and per output event one await per post-hook (two system plus agent hooks); each default is a pass-through.

## Testing

New files:

- `tests/test_runtime_hook_api.py`: `Runtime.run_pre_hooks` (order agent then system, halt returns the reply, wrong type `TypeError`, unchanged from `run()`); `run_stream_input_hooks` (default pass-through, `None` drops, a list ends the chain and splits voice/text, wrong single type and wrong list item raise naming the hook, agent hooks before system hooks); `run_stream_event_hooks` (same chain semantics as `Runtime.stream`: `None` drops, a list ends the chain, a different `type` raises, system hooks before agent hooks); `Runtime.stream` still warns when a post-hook drops `RunPaused` (the `last_hook` name reaches the warning).
- `tests/test_realtime_hooks.py`, built on the fakes of `tests/test_realtime_pool.py` (`_Adapter`, `_Agent`, `_connection`, `_drain_output`, `_kinds`, the `asyncio.to_thread` patch):
  - Output: a recording post-hook sees every event type in order; rewriting a `TextDelta`; dropping audio; a list replacing an event; `MessageEnd` reaches hooks before `done`, with the last event's `message_id` or a fresh one; a hold-and-release hook releases at `MessageEnd`; an `Interrupt` reaches a holding hook before later events; pacing follows emitted audio (dropped audio does not sleep, longer replacement audio sleeps longer); `StreamHalt` and a raising hook send one error chunk and close the connection with the pacing task not cancelling itself.
  - Input: a recording pre-hook sees audio with its `name`; `None` drops (the adapter gets nothing); a returned list of voice goes to the adapter at the model's rate; a returned `AgentRequestText` goes through `run_pre_hooks` and is sent once; typed text runs agent then system hooks; a pre-hook halt sends the error chunk and nothing to the adapter; a raising text hook sends the generic error chunk; a raising audio hook drops the chunk and logs once at `ERROR`; `Session.current()` and `Agent.current()` are set inside every hook call.
  - `close()` clears the volatile cache; `initialize()` warns once per realtime agent when `guardrail.input.enabled` (config stubbed with a real `_GuardrailConfig`, never a bare namespace) and stays silent when it is off.

Existing tests that change:

- `tests/test_realtime_pool.py`: `_kinds(...)` sequences gain `message_end` before each `done`: `:827` (`["agent_changed", "audio_delta", "message_end", "done"]`), `:851` (same), `:887` (two turns, so two `message_end`). `:757-761` still passes (`kinds[-1] == "done"`, three audio deltas). `:729` builds `AgentRequestVoice(audio_data=..., name="clip")` for `conn.append_audio`. The stub `TestDispatchPrincipal._Conn` (`:431-447`) takes request objects and records `request.prompt`, so `:464` keeps asserting `["hi"]`.
- `tests/test_realtime_edge_path.py`: the `order` list (`:66-77`) gains `message_end` before each of its two `done`.
- `tests/test_runtime.py`, `test_runtime_stream_events.py`, `test_runtime_resume*.py`: unchanged and must pass (the refactor is behaviour-neutral); no test patches `_prepare_requests`.
- Not changed, to be re-run: `test_adk_realtime.py`, `test_openai_realtime.py`, `test_livekit_edge_adapter.py`, `test_livekit_lifecycle_adapter.py`, `test_ecs_akagentrunner_realtime.py`, `test_module.py`.

Run: `cd ak-py && uv run pytest tests/test_runtime_hook_api.py tests/test_realtime_hooks.py tests/test_realtime_pool.py tests/test_realtime_edge_path.py tests/test_runtime.py tests/test_runtime_stream_events.py`, then `uv run pytest`, then `make lint-check`.

## Design requirements traced

| design.md requirement | Spec section |
| --- | --- |
| Caller text through `on_run`, halt becomes an error chunk | 3.3 (typed text) |
| `on_stream_input`, return rules, edge-rate audio, agent then system order | 1, 2, 3.3 (audio) |
| Text item from an audio hook is handled as typed text | 1, 2, 3.3 |
| Output through `on_stream_event`, system then agent, `TypeError` on a type change | 2, 3.2 |
| `MessageEnd` at turn end, `done` not an event, `Interrupt` in order | 3.2 |
| `StreamHalt` ends the call | 3.2, 3.4 |
| `requests` is the last text turn, else `[]` | 3.2 (`_last_turn`), 3.3 |
| `Session.current()` / `Agent.current()` set, state in the volatile cache | 1, 3.1 |
| `Runtime` owns the loops, public methods, no behaviour change | 2 |
| No new class; methods on `RealtimeConnection` / pool | 3, 3.6 |
| One startup warning (input guardrail) | 3.6 |
| No config, extra or provider | Config changes |
| Hooks-per-mode docs; stale "hooks do not run" statements | Plan, docs iteration |
