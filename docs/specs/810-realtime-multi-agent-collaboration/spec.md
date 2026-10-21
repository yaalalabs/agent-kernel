# #810: Realtime multi-agent collaboration — Implementation Spec

> OpenAI native-engine extension: earlier statements that OpenAI is unchanged are
> superseded by [the migration research](research/openai-native-realtime.md) and the
> “OpenAI native realtime extension” in design.md. Voice declarations use RealtimeAgent;
> the SDK owns execution, and the shared pool receives paced-audio tracking notifications.


Implements the requirements in [`design.md`](design.md). The realtime pool keeps each call's turn state, says
application text only into a quiet call (`RealtimeCall.send_if_quiet`, the application keeping what waits), and feeds
`RealtimeObserver`s. The Gemini
adapter runs each call on ADK's own live engine (`Runner.run_live`): ADK runs the tools and their callbacks, transfers
and keeps the conversation, in the pool's tool scope, and the adapter starts a run that failed again. A connection owns its tool calls, so a tool that awaits long work (another
agent's run) is cancelled with its call. The LiveKit gateway signs participant tokens. The idea: voice is the meeting
room, not the engine.

## Verification performed for this spec

Each item was checked against `develop` at `4c78c482`, the branch at `58015003`, the installed `google-adk==2.8.0` and
`google-genai==2.21.0`, the `google-adk==1.24.0` wheel (the floor, `ak-py/pyproject.toml:128`), or the Live API docs.

- ADK 1.24.0 and 2.8.0: `RunConfig` has `realtime_input_config`, `input_audio_transcription` and
  `output_audio_transcription`; `google.adk.flows.llm_flows.contents._present_other_agent_message` exists in both
- ADK's tool-callback order (2.8.0, `google/adk/flows/llm_flows/functions.py:621-682`): before-callbacks run until one
  returns a truthy result; the tool runs when the result is still `None`; error callbacks run until one returns non-`None`,
  else the error is raised; after-callbacks run until one returns a truthy result, which replaces the response when non-`None`
- google-genai 2.21.0: `LiveConnectConfig` has `realtime_input_config`
- Live API ([Session management](https://ai.google.dev/gemini-api/docs/live-session), 2026-10-15): a connection lasts about
  10 minutes, then the server closes it; each new connection is a new session
- `develop` behaviour this change replaces
  - A Gemini socket error is reported as `error` (`adk.py:1219-1234`); `RealtimeConnection._fail` closes the connection
    (`realtime_pool.py:159-171`); the next input opens one at the entry agent (`:95-98`)
  - Audio and text are dropped while no socket is open (`adk.py:1298-1308`, `:1360-1361`)
  - `ToolContext.set()` keeps the reset token on the instance (`core/tool.py:102-116`)
  - The pool's sweep skips closed connections (`realtime_pool.py:401`); a closed one is closed only when its session
    sends more input (`get_connection`, `:441-453`)
- `agentkernel.pipeline` exports `RealtimeCall` and no other `realtime_pool` name (`pipeline/__init__.py`)
- The `RealtimeRunner` callback contract (`core/realtime/runner.py`) documents `speech_heard`, `speech_stopped` and
  `caller_transcript`, not `reconnected` or the `done` status `reconnecting`
- `LiveKitEdgeGateway.__init__` raises without a token or an API key and secret, and contacts no server
  (`integration/livekit/adapter.py`, `_single_participant`); the example builds its gateway only under `__main__`,
  so its tests import it without LiveKit settings
- CI runs each example listed in `.github/test-config.yaml` with `./build.sh local`, the branch's own build, then
  `uv run pytest -s` (`.github/scripts/run_single_test.py:87-112`); no `examples/api/livekit-voice/*` example was listed
- AG-UI cannot carry a voice call: `ag-ui-protocol` 0.1.22 has no audio events, AK's AG-UI handler answers one HTTP
  request per run (`integration/agui/handler.py:221`) on the stream path, and rejects audio input (`run_input.py:216`)

Checked for the native ADK path (installed `google-adk==2.8.0`; the 2.6.0, 2.7.0, 2.11.0 and 2.12.0 wheels):

- `handle_function_calls_live` runs each call of a tool-call message as its own `asyncio` task, and the plugins'
  `before_tool_callback` runs first in that task, before the agent's callbacks (2.8.0
  `flows/llm_flows/functions.py:717-934`; 2.11/2.12 `flows/llm_flows/tools/_live_caller.py`)
- `run_live` awaits the tool calls inside its receive loop (2.8.0 `base_llm_flow.py:1611`): nothing is read from the
  socket while a tool runs
- A transfer is performed on the result's `actions.transfer_to_agent` from 2.7.0 (2.8.0 `base_llm_flow.py:784`);
  2.0.0 to 2.6.0 close the socket on any `transfer_to_agent` result, so a refused transfer ends the run. The floor is
  therefore `google-adk>=2.7.0`, confirmed by running `test_adk_realtime.py` on 2.6.0 (the refused transfer fails),
  2.7.0, 2.8.0 and 2.11.0 (all pass)
- The live connect config takes `speech_config` from the `RunConfig` or the agent's `Gemini` model object
  (`flows/llm_flows/basic.py:145`, `models/google_llm.py:518`), not from `generate_content_config`
- The contents processor turns finished transcriptions into text turns, so a new socket is given what was said;
  ADK's Gemini connection marks a transcription finished on Gemini's `finished`, `turn_complete`, `interrupted` or
  `generation_complete` (`models/gemini_llm_connection.py:435-530`)
- ADK resumes a dropped socket when it holds a session resumption handle (up to 5 attempts); transparent resumption is
  set only on Vertex AI (`base_llm_flow.py:651-690`). Gemini 3.1 Live sent handles in live runs without being asked

## Design

### Package layout

```
ak-py/src/agentkernel/
├── livekit.py                 # NEW: public alias of integration.livekit
├── core/
│   ├── __init__.py            # exports RealtimeEvent, RealtimeObserver
│   └── realtime/
│       ├── observer.py        # NEW: RealtimeEvent, RealtimeObserver
│       └── runner.py          # reports_speech_stopped; runs_tools / use_tool_scope; the new adapter events
├── framework/
│   ├── adk/adk.py             # GoogleADKRealtimeRunner on Runner.run_live; the ADK tool wrapper
│   └── openai/openai.py       # speech_stopped
├── integration/
│   └── livekit/adapter.py     # participant_token
└── pipeline/
    ├── __init__.py            # exports RealtimeCall
    └── realtime_pool.py       # turn state, the quiet rule and guarded send, the tool scope, RealtimeCall, observers, recovery readiness, sweep
```

### Core contracts (`core/`)

```python
class RealtimeEvent(BaseModel):
    type: Literal["connected", "caller_said", "edge_text", "agent_said", "agent_changed", "reconnected", "disconnected"]
    session_id: str
    agent: Optional[str] = None
    text: str = ""
    interrupted: bool = False
    at: float = Field(default_factory=time.time)

class RealtimeObserver(ABC):
    async def on_event(self, session: Session, agent: Agent, event: RealtimeEvent) -> None: ...
    def name(self) -> str: ...

class RealtimeCall:   # pipeline/realtime_pool.py
    @staticmethod
    def observe(observer: RealtimeObserver) -> None: ...     # process-wide; each new connection takes the list
    @staticmethod
    def unobserve(observer: RealtimeObserver) -> None: ...

class RealtimeRunner:
    reports_speech_stopped: bool = False   # True only where the model signals the end of the caller's speech
    runs_tools: bool = False               # True where the framework runs the model's tool calls itself
    def use_tool_scope(self, open_scope: Callable[[], Awaitable[ToolContext]]) -> None: ...   # set by the pool
    # execute_tool / send_tool_result: no longer abstract; required unless runs_tools

class RealtimeConnection:   # pipeline/realtime_pool.py
    async def open_tool_scope(self) -> ToolContext: ...   # from the framework's task running one tool call
```

Rules:

1. `core/realtime/observer.py` imports nothing outside `core/` and pydantic; `core/hooks.py`, `Agent` and `Module` are unchanged.
2. The adapter callback contract (`RealtimeRunner` docstring) gains, none reaching the edge:
   - `speech_heard {}`: the caller is still speaking;
   - `speech_stopped {}`: the caller stopped; only from an adapter with `reports_speech_stopped`;
   - `caller_transcript {"text"}`: optional, the caller's words in one turn;
   - `reconnected {"agent", "seconds", "seeded"}`: the socket was replaced and is answering, with `seeded` true when the new socket was given the conversation;
   - `done` with status `reconnecting`: the turn under way ended because the socket was lost.
3. Observers live on the pool class (`RealtimeConnectionPool._observers`), not on `Agent`: a call is observed, not an agent, and the list can be filled before the pool starts. `get_or_create` passes it to each new `RealtimeConnection(..., observers=)`.
4. `set()` / `reset()` are unchanged for their callers, which activate once per run.
5. An adapter with `runs_tools` reports no `tool_call`. The pool calls `use_tool_scope(self.open_tool_scope)` before
   `connect()`. `open_tool_scope()`, awaited from the task running one tool call, counts the call as running, adds the
   task to `_tool_tasks`, starts a holder task (`_hold_tool_scope`) that holds `async with session` and keeps the
   `ToolContext` fetchable, waits until the holder has the lock or has ended (a holder ended first raises
   `RuntimeError`), then sets `Session.current()`, `Agent.current()` and the `ToolContext` in the calling task's own
   context. The task's done-callback ends it all: the holder lets go, the count drops, a holder still waiting for the
   lock is cancelled, and a task not cancelled marks `last_tool_result_at`.

### ADK realtime runner (`GoogleADKRealtimeRunner`)

`runs_tools = True`. Per call, `connect()` creates an `InMemorySessionService` session named after the AK session, a
`Runner(app_name="AgentKernel", agent=<the starting agent>, plugins=[_ToolScope, *declared plugins], **declared
options)` (the starting agent's `GoogleADKRunner.RUNNER_CONSTRUCTOR_OPTIONS` run options), the call's `RunConfig` and a
`LiveRequestQueue`, then starts `_supervise()` and the stall watchdog and returns: ADK opens the socket on that task.

#### The call's settings

- `RunConfig`: a copy of the starting agent's `run_config` run option, else `RunConfig()`; `response_modalities`
  defaults to audio, and input and output transcription are turned on when unset. Everything else is ADK's
- Voices come from each agent's model object; nothing is read from `generate_content_config`

#### Input

- `append_audio` → `LiveRequestQueue.send_realtime(Blob)`; `send_text` → `send_content(Content(role="user"))`. The queue
  holds both while no socket is open; ADK sends text as each Live model takes it

#### Tools

- `_ToolScope(BasePlugin)`, the first plugin: `before_tool_callback` calls `_enter_tool(tool.name, agent)`, which
  refuses to run on the live run's own task (`RuntimeError`: the scope would hold the session for the whole call),
  logs the call, counts it for the stall watch and awaits the pool's `open_tool_scope()`. `after_tool_callback` and
  `on_tool_error_callback` log the result or the error and return `None`, so they change nothing

#### Events reported (`_report`)

| ADK event | Reported |
|---|---|
| The first event of a restarted run | `reconnected {"agent", "seconds", "seeded": True}` |
| Caller transcription (partial or final) | `interrupt` while the model speaks (once per turn), else `speech_started` once per caller turn, then `speech_heard`; a final one is also `caller_transcript` and logged |
| `interrupted` | `interrupt`, once per turn |
| A partial output transcription | `transcript_delta` (the finished, whole one is not repeated) |
| Audio in the content of a model event | `audio_delta` |
| A function response carrying `actions.transfer_to_agent` | `done {"status": "transferred"}`, then `agent_changed` |
| A model event from another agent than the one with the call | `agent_changed` (a restarted run resumed another agent) |
| `turn_complete` | `done {"status": "completed"}` |

No `tool_call` is reported.

#### Recovery

| Constant | Value | Meaning |
|---|---|---|
| `RESTART_DELAYS_SECONDS` | (1, 2, 4) | Wait before each restart; their number is also the quick drops in a row that give up |
| `QUICK_DROP_SECONDS` | 20 | A run lost this soon after a restart is a quick drop |
| `STALL_SECONDS` / `STALL_CHECK_SECONDS` | 25 / 1 | No model progress this long, while it owes an answer and no tool runs, is a stall; checked this often |
| `SPEECH_LEVEL` | 500 | RMS of 16-bit samples above which caller audio sent while the line is down is speech |
| `RECONNECTED_NOTE` / `RECONNECTED_QUIET_NOTE` | text | The note when the caller spoke / did not; `""` adds none |

`_supervise()` runs `_run_live()` (`Runner.run_live` over the queue, each event to `_report`) as a task and waits for it.
A run cancelled by the call closing ends it; a run that ended, raised, or was cancelled by the watchdog (`_stalled`)
calls `_restart(reason)`:

1. Mark the line down; keep whether the caller spoke while it was down, or had said something the model had not
   answered (`_caller_said_at` later than `_model_said_at`); end the turn; report `done {"status": "reconnecting"}`.
2. After as many quick drops in a row as there are delays, report `error` and stop.
3. Wait the next delay (stop if closing), queue the note, keep the time of the first loss, and return: `_supervise()`
   starts the run again. ADK resumes the agent that last had the call (`Runner._find_agent_to_run`) with its session.
4. The new run's first event reports `reconnected` with the seconds since the first loss. A run that fails before
   sending one is restarted in turn and is never reported.

Rules:

1. **Stall wait.** `_owed_since` is set on a caller's final transcription, text sent, a tool's result (its task ended),
   a queued note, and each model audio or transcript; cleared on `turn_complete`, `interrupted`, a tool call and while
   any tool runs. Text sent while a wait is running does not restart it.
2. **ADK owns the socket.** Session resumption (with a handle), the history a new socket is given, transfers and their
   delay are ADK's; the adapter never opens, closes or seeds a socket.
3. **Shutdown.** `disconnect()` stops the watchdog, closes the queue, cancels `_supervise()` (and with it the run) and
   closes the `Runner`. It is safe before `connect()` and twice.

### OpenAI realtime runner (`OpenAIRealtimeRunner`)

`reports_speech_stopped = True`; `input_audio_buffer.speech_stopped` reports `speech_stopped`. Nothing else changes.

### Realtime pool (`pipeline/realtime_pool.py`)

#### Turn state (`RealtimeConnection`)

| Adapter event or call | Updates |
|---|---|
| `audio_delta`, `transcript_delta` | `last_model_generated_at`; response open; `last_model_output_at` when paced out to the edge |
| `agent_changed` | `last_agent_change_at` |
| `done`, `interrupt`, `speech_started` | response closed |
| `interrupt`, `speech_started`, `speech_heard`, `speech_stopped` | `last_caller_speech_at`; `is_caller_speaking` set by the first two when `reports_speech_stopped`, cleared by `speech_stopped` or model audio |
| `done` with status `reconnecting` | recovering |
| `reconnected` | not recovering; when `seeded`, `last_reconnect_at` |
| a tool call / its result sent | `_tools_in_flight` up / down; `last_tool_result_at` |
| `send_text(text, from_edge=True)` | `last_edge_text_at`; an `edge_text` observer event |

- `is_responding`: queued output, a tool in flight, or a response open with model output in the last `_UNFINISHED_RESPONSE_SECONDS` (15 s)
- `is_ready`: connected, not closed, not recovering
- `agent_has_spoken`: `last_model_generated_at` is later than `last_agent_change_at`

#### The quiet rule and the guarded send (`RealtimeConnection`)

Constants: `_QUIET_SECONDS = 1.5`, `_REPLY_WAIT_SECONDS = 15.0`; the pool's loop wakes every `_TICK_SECONDS = 0.25`
for its sweep and lag check.

- `awaiting_reply(now)`, **inferred**: one of `last_caller_speech_at`, `last_edge_text_at`, `last_tool_result_at`,
  `last_reconnect_at` or `last_post_at` is later than `last_model_generated_at` and younger than `_REPLY_WAIT_SECONDS`.
  An input past that wait stops counting: the pool stops waiting; it never records a reply as given.
- `quiet_since(now)`: `None` while not `is_ready`, `is_responding`, `is_caller_speaking` or `awaiting_reply`; else the
  newest of `connected_at`, `last_model_output_at`, `last_caller_speech_at`, `last_edge_text_at`, `last_tool_result_at`,
  `last_reconnect_at`, `last_agent_change_at` and `last_post_at`. Its value names the quiet stretch.
- `send_if_quiet(text, quiet_since=None)`, on the pool loop: `False` unless `quiet_since(now)` is not `None`, is
  `_QUIET_SECONDS` old, and equals `quiet_since` when given; else set `last_post_at`, await `adapter.send_text(text)`
  (on failure restore `last_post_at` and re-raise) and return `True`. Check and send are one step on the loop.
- Each connection has its own `last_post_at`, so a new connection owes nothing to text sent into the old one.

#### `RealtimeCall` and the pool's API

| `RealtimeCall` | Through the pool | Without a pool or a live call |
|---|---|---|
| `await send_if_quiet(text, *, quiet_since=None) -> bool` | runs the connection's `send_if_quiet` on the pool's loop (`run_coroutine_threadsafe` + `wrap_future` from another loop) | `False` |
| `connected` | `live_connection(session_id)` exists | `False` |
| `quiet_since() -> float \| None` / `quiet_for() -> float \| None` | from the live connection | `None` |
| `agent_has_spoken -> bool \| None` | as on the connection | `None` |
| `close() -> bool` | pops the connection, closes it on the loop | `False` |

The pool's lookups for it: `open_connection(session_id)` (not closed: ready, connecting or recovering) and
`live_connection(session_id)` (ready).

#### Observers

- A connection with observers gets an `asyncio.Queue` and one task; `_observe` puts on the loop, `_observe_soon` from other threads
- Sources: `connect()` (`connected`); the pacing loop (`agent_changed`, `agent_said` at `done`, `interrupt` or a change); `caller_transcript` (`caller_said`); `send_text(from_edge=True)` (`edge_text`); `reconnected`; `close()` or a failure (`disconnected`, once)
- On close, the observers get `_OBSERVER_DRAIN_SECONDS` (2 s), then the task is cancelled

#### Sweep and loop lag

- Every 5 s the loop pops and closes connections idle for `_IDLE_TIMEOUT_SECONDS` (300 s) **and** connections already closed by a failure
- The loop measures its own sleep; lag beyond `_LOOP_LAG_WARNING_SECONDS` (1 s) logs a warning

### LiveKit gateway (`LiveKitEdgeGateway`)

- `AGENT_IDENTITY_PREFIX = "agent-"`; agent identities are built from it
- `participant_token(identity, name=None, **grants)`: `ValueError` for an identity starting with the prefix, for `room` or `room_join` in `grants`, and with no key and secret; else `_sign(identity, name, **grants)`
- `_sign` builds `api.AccessToken(...).with_identity(...)`, adds the name when given, and grants `VideoGrants(room_join=True, room=self.session_id, **grants)`; `_mint_token` uses it with `can_update_own_metadata=True`

### Packaging

- `agentkernel/livekit.py` re-exports `integration.livekit`, as `slack.py` does
- No new extra; the `adk` extra's floor rises to `google-adk>=2.7.0` (`ak-py/pyproject.toml`, the matching specifier in
  `ak-py/uv.lock`; the locked 2.8.0 is unchanged)

### Example (`examples/api/livekit-voice/google/handoffs/`)

| File | Change |
|---|---|
| `server.py` | `verify_account(account_id, tool_context)`, a supervisor tool, keeps a verified account in the ADK tool state, which lasts for the call across transfers; `require_account`, the supervisor's `before_tool_callback`, answers in place of `transfer_to_agent` to `billing` or `tech_support` until an account is verified; `book_technician`, an `async` tool, waits for the dispatch system and answers with the confirmation (Application building blocks, Example); a `CallLog(RealtimeObserver)` logging `caller_said`, `agent_said`, `agent_changed` and `reconnected`, registered with `RealtimeCall.observe` under `__main__`, where the gateway is built; each agent's voice from its model, `voice()` returning `Gemini(model=..., speech_config=...)` |
| `server_test.py` (new) | Offline tests (Testing) |
| `README.md` | Refusing a handoff, a tool that waits, the call log, the walkthrough, tests; ADK's own live runner, and the limits of its transfer |

`.github/test-config.yaml`: `- type: api` / `path: examples/api/livekit-voice/google/handoffs`; the tests need no
model, LiveKit server or key.

### Application building blocks

Verified for this part against the branch at `d1a464bd` and the installed `openai-agents==0.20.0` and
`google-adk==2.8.0`: `GoogleADKToolBuilder._wrap` keeps a coroutine function a coroutine function (`adk.py`, the
`asyncio.iscoroutinefunction` branch), and ADK's `FunctionTool.run_async` awaits it, so an `async` tool runs on the
pool's loop; `OpenAIRunner.run` catches `Exception` (a framework error becomes error text) but not
`asyncio.CancelledError`, and resets its `ToolContext` in `finally`; `Session.__aexit__` resets the current session
from its own token and releases the lock on any exit, cancellation included (`core/base.py`), as `Agent._activate`
does for the current agent. `Runtime._current` is class-level (`core/runtime.py:155`). No change to `core/model.py`,
`core/runtime.py` or the framework adapters' unary paths (design.md Non-goals).

```
ak-py/src/agentkernel/
├── core/
├── integration/adapter/gateway.py  # GatewayRunner.stop
└── pipeline/
    ├── realtime_pool.py         # RealtimeCall facts; tool calls the connection owns; the stretch a send is for
    └── __init__.py              # RealtimeCall's lazy export points at realtime_pool
```

#### Module layout (`pipeline/realtime_pool.py`)

- The pool stays in `pipeline/realtime_pool.py`, where agentkernel 0.9.5 shipped `RealtimeConnectionPool` and
  `RealtimeConnection`: their imports, the module settings its tests patch (`_SHUTDOWN_GRACE_SECONDS`, ...) and the
  logger (`ak.pipeline.realtime_pool`) are unchanged. Line citations to `realtime_pool.py` earlier in this spec refer to
  the file before this change
- The public path is `agentkernel.pipeline` (`RealtimeCall`), whose lazy export points at `realtime_pool`
- `core/realtime/` keeps the adapter contracts and audio primitives; the gateways stay in `integration/adapter/`

#### Tool calls the connection owns (`pipeline/realtime_pool.py`)

```python
_TOOL_CANCEL_SECONDS = 2.0

class RealtimeConnection:
    _tool_tasks: set[asyncio.Task]                  # the tool calls still running
    async def close(self) -> None: ...               # also cancels them, before the adapter disconnects
```

Rules:

1. **Owned.** `handle_framework_event("tool_call", ...)` creates `_execute_tool_and_reply` as a task of the
   connection, adds it to `_tool_tasks`, and removes it when it is done (`add_done_callback(discard)`). A tool an
   adapter's framework runs (`runs_tools`) is added by `open_tool_scope()` (Core contracts, Rule 5).
2. **Busy.** A running tool call counts toward `_tools_in_flight`, so `is_responding` is true: `send_if_quiet` declines
   and `quiet_for()` is `None`. Unchanged; a tool that awaits long work makes it last.
3. **Closing.** `close()` sets `closed` and, the first time, stops pacing, then `_cancel_tools()`: cancel every
   running tool task except the current task (a tool that closes its own call), `asyncio.wait` them up to
   `_TOOL_CANCEL_SECONDS` (a warning for those still running), then `adapter.disconnect()`. The cancellation reaches
   the tool's awaits, so a nested `AgentService.run_multi` unwinds its own session and context; the tool's
   `async with session` and `Agent._activate()` then unwind the call's.
4. **No late result.** `_execute_tool_and_reply` sends the result only while `closed` is false: a tool that finished
   once the connection was closed or its socket failed (`_fail`), even one that ignored its cancellation, is logged
   and its result dropped. `last_tool_result_at` moves only for a result that was sent. A cancelled tool sends
   nothing and its `CancelledError` propagates out of its task.
5. **Recovered sockets.** A socket the Gemini adapter replaces itself leaves the connection open (`closed` false).
   ADK notices a lost socket only once its tools have returned, so their results are in the conversation the
   restarted run is given, and no tool is run again.
6. **Nothing else.** No time limit, no retry, no queue: the tool's own code bounds its wait.

#### Call facts and sends for one quiet stretch (`pipeline/realtime_pool.py`)

```python
class RealtimeCall:
    last_caller_input_at: Optional[float]           # max(last_caller_speech_at, last_edge_text_at)
    last_agent_change_at: Optional[float]
    last_tool_result_at: Optional[float]
    def quiet_since(self) -> Optional[float]: ...
    async def send_if_quiet(self, text, *, quiet_since=None) -> bool: ...
    def close(self) -> bool: ...                     # the connection's close() cancels its running tool calls
```

Rules:

1. The facts read the session's open connection (`closed` false), ready or recovering; `None` without one.
2. `quiet_since()` / `quiet_for()` read the live connection's `quiet_since(now)`; `quiet_for` is `now - quiet_since`.
3. No quiet-call event: an application polls `RealtimeCall.quiet_for()` (from a task on the realtime loop that an
   observer starts on `connected` and cancels on `disconnected`).
4. `quiet_since` takes `last_agent_change_at` with the other times: a handover ends a quiet stretch.
5. Text for one quiet stretch: the application keeps `quiet_since()` with it and passes it to `send_if_quiet`, which
   declines once the current stretch differs, which a new connection also makes it (its `connected_at`).
6. `GatewayRunner` unregisters with `StatefulEdgeRegistry.unregister(session_id, adapter=...)`, which removes the
   entry only while it is that adapter.

#### Gateways (`integration/adapter/gateway.py`)

```python
class GatewayRunner:
    def stop(self, timeout: Optional[float] = None) -> bool: ...   # whether start() has returned (or never ran)
```

Rules:

1. `stop()` sets a `threading.Event`; `_run_until_shutdown` ends on it as on the shutdown event, stopping the adapter on
   its own loop. `start()` after `stop()` returns at once, registering nothing. `stop(timeout)` waits for `start()` to
   return when it has begun.
2. A gateway per session is the application's: it keeps a `GatewayRunner` per session under its own lock, hosts each
   on a daemon thread running `start()`, forgets the entry when `start()` returns or raises (only if it is still its
   own), and calls `stop(timeout)` outside the lock.

#### Example (`examples/api/livekit-voice/google/handoffs/server.py`)

- `book_technician(account_id, day)` is `async`: it awaits `Dispatch.book`, which sleeps `DISPATCH_SECONDS` (the
  dispatch system's time) and returns the confirmation as the tool's result; a second booking for an account already
  being booked is refused (two calls in one model turn). No thread, no post

### Consumer changes

- `RealtimeConnectionPool.dispatch`: text requests call `send_text(prompt, from_edge=True)`; the ECS realtime agent runner goes through `dispatch` (its test assertion changes)
- `RealtimeConnection.send_text` gains a keyword-only `from_edge=False`; other callers are unchanged
- LiveKit examples: public aliases; the `sqs` token handlers call `participant_token`

### Config changes

- No new fields, models, extras or env vars; existing YAML and `AK_*` variables are unaffected

### Behavioural changes

1. ADK realtime calls run on ADK's `Runner.run_live`: ADK runs the tools with their plugins and callbacks, transfers and keeps the conversation. Intentional, the feature.
2. A Gemini socket ADK cannot resume, or a stalled one, restarts the run with the same agent instead of failing the call and restarting at the entry agent. Intentional.
3. Audio and text sent while no Gemini socket is open wait in ADK's queue for the next one, instead of being dropped; what the caller says in ADK's transfer delay goes to the agent handing over. Intentional, ADK's behaviour.
4. A new socket is given teammates' turns as user-side `[agent] ...` context and the agent's own turns as its own, ADK's presentation. An agent's voice comes from its model (`Gemini(speech_config=...)`), no longer from `generate_content_config`. Intentional, ADK's behaviour.
5. The ADK adapter reports `speech_started`, `speech_heard` and `caller_transcript`; the OpenAI adapter reports `speech_stopped`. None reaches the edge; `speech_started` is a barge-in only while paced audio is queued, as before.
6. The call's `RunConfig` and ADK `Runner` options (plugins, services) come from the starting agent's run options. Without them it is as before, transcription on.
7. The pool's loop wakes every 0.25 s instead of 0.5 s; the idle sweep still runs every 5 s and now also closes failed connections.
8. LiveKit agent tokens are signed through `_sign`, with the same claims.
9. Closing a realtime connection cancels its running tool calls, and a result that comes once it is closed or its socket failed is not sent. Before, such a tool ran on with the session lock, and its result went to the disconnected adapter. Intentional.
10. No `Module.realtime_hook` / `Agent.realtime_hooks`: observers are registered with `RealtimeCall.observe`. Nothing of the hook API was released.

**Non-changes:** the reply models and every adapter's error reply; the existing `RealtimeCall` members; `GatewayRunner.start()` for a runner never stopped; `IOHandler.run(gateways=...)`; the stream event union and `AgentChanged`'s fields; queue message formats; OpenAI handoffs and the
LiveKit gateway's participants; `ToolContext.set()` / `reset()`; `AKConfig`; the extras; other examples' behaviour.

## Error handling

| Condition | Where | Surfaces as |
|---|---|---|
| A socket drops with a resumption handle | ADK's `run_live` | resumed by ADK; nothing reported |
| A run ends, fails or stalls | `GoogleADKRealtimeRunner._supervise` / `_restart` | `done {"status": "reconnecting"}`, then `reconnected` on the restarted run's first event; observers get `reconnected` |
| Restarted runs lost quickly, three times in a row | `_restart` | `error` ("keeps dropping") → the pool fails the connection; the edge gets an error chunk |
| A tool raises with no error callback answering | ADK | ADK's error response to the model |
| A tool scope opened on the live run's own task | `_enter_tool` | `RuntimeError`: an ADK version that runs tools inline is not supported |
| A tool scope's holder ends before it has the lock | `open_tool_scope` | `RuntimeError` in the tool |
| A realtime observer raises | `_serve_observers` | logged; the next observer runs |
| An observer is still busy at close | `_finish_observers` | warning after 2 s; its task cancelled |
| `send_if_quiet` with no pool or no live call | `RealtimeCall` | `False`; nothing kept |
| `send_if_quiet` into a busy call or a moved-on stretch | `RealtimeConnection.send_if_quiet` | `False`; nothing kept |
| The adapter's send fails | `RealtimeConnection.send_if_quiet` | raised to the caller; `last_post_at` unchanged |
| `participant_token` misuse | `LiveKitEdgeGateway` | `ValueError` |
| A tool still running when its connection closes | `RealtimeConnection.close` | cancelled (info log); no result sent |
| A cancelled tool still running after 2 s | `_cancel_tools` | warning; the adapter disconnects; its result is never sent |
| A tool finishes after its connection closed or its socket failed | `_execute_tool_and_reply` | info log; result not sent |

## Testing

### Changed: `ak-py/tests/test_realtime_pool.py`

- `TestRealtimeTurnState`: each row of the turn-state table; a pause mid-answer; a lost `done`; readable from another thread; `is_ready` false between `reconnecting` and `reconnected`
- `TestOpenAIBargeIn`: the OpenAI adapter's caller events
- `TestRealtimeToolScope`: a tool run by the adapter's framework gets the call's scope until its task ends; one cancelled while the session is busy leaves no holder behind; a holder ended before it had the lock fails the tool
- `TestRealtimeQuietCall`: busy, unready, recovering and output-pending calls; owed replies to each kind of input, the wait ending without a reply recorded; words generated before a tool result no answer to it; a handover starting a stretch
- `TestRealtimeCall`: posts with and without a call; `quiet_for`, `agent_has_spoken`; no pool; `close()` with and without a pool
- `TestRealtimeObservers`: events from connect to close, `reconnected` included; a failing observer; edge text from another thread; no observers, no queue; observers registered with `RealtimeCall.observe` reach the connections made after
- The pool: the sweep closes a failed connection without further input; the loop-lag warning

### New in `ak-py/tests/test_realtime_pool.py`

- `TestRealtimeAwaitedTools`: a tool awaiting a nested run in a session of its own keeps the call busy (no post said,
  `quiet_for()` is `None`), its result is sent once and the call's session and agent are current again after it; closing the
  connection, directly or through `RealtimeCall.close()`, cancels it, releases both sessions' locks, leaves no task and
  sends nothing; a tool that ignores its cancellation still sends nothing; a result after a failed socket is not sent

### New: `ak-py/tests/test_adk_realtime.py`

ADK's real `run_live` through a `RealtimeConnection`, against a scripted Gemini Live socket standing in for
`google.genai.Client`:

- Talking: a turn's events and observations, text sent as ADK sends it, one interrupt per turn, each agent's voice and
  the call's `RunConfig` on its sockets
- Tools: a bound tool runs once in the call's scope (and is logged), an ADK tool gets ADK's `ToolContext`, the calling
  agent's before / error / after callbacks once each, a tool asking another agent in a session of its own, a waiting
  tool keeping the call busy and holding the session, closing during a tool, two calls at once, the application's
  plugins inside the scope
- Handoffs: a three-agent handoff with the conversation carried over and each socket's voice, a refused handoff
  keeping the agent and its socket open, the caller's audio in and after ADK's transfer delay, words said with a
  transfer with and without their transcription end, the team
- Recovery: ADK resuming with a handle, a drop restarting the same agent with the conversation and a note, the note
  chosen by whether the caller's words were answered, a finished tool not run again, a stall restarted, a slow tool
  not a stall, quick drops given up on, a restart reported only once its run says something, closing while restarting
- Lifecycle: disconnect safe twice and before connect, a socket that cannot open failing the call, the tool scope
  refused on the run's own task

### Changed: other files

- `test_livekit_gateway.py`: participant tokens (room, grants, refusals, no key); the alias
- `test_ecs_akagentrunner_realtime.py`: `send_text(..., from_edge=True)`
- `test_realtime_pool.py`: `TestRealtimeCallFacts` (each fact; `None` without a connection; read while recovering); `TestRealtimeCall` (`send_if_quiet`: sent once quiet then owed a reply, declined and nothing kept while the caller speaks, output is pending, a tool runs or the socket recovers, a moved-on stretch declined, a failing send raising, a send from another event loop run on the pool's); `TestOpenAIRealtimeToolGuards` unchanged (approval and any tool guardrail excluded)
- `test_integration_gateway_runner.py`: `stop()` from another thread, before `start()`, and its wait; a failed start leaving nothing registered, a slowly leaving gateway not unregistering its replacement
- Lifecycle cases (`test_realtime_pool.py`): a send declined while the socket recovers and accepted once it is back

### New: `examples/api/livekit-voice/google/handoffs/server_test.py`

- `require_account` answers in place of a transfer to a specialist until the account is verified, then lets it through; other tools and other transfers pass
- `verify_account` records a verified account in the tool state and refuses a malformed one
- `book_technician` answers with the confirmation once the dispatch system's wait ends, and refuses a second booking for the account made at the same time
- `require_account` is the supervisor's callback; `CallLog`, a realtime observer, logs both sides of the call

### Live check

On `gemini-3.1-flash-live-preview`, with the application's researcher and reviewer on `gpt-4.1`: a handoff refused by
a callback, research and a review awaited by a voice tool (how long the caller waits, and what they hear), a forced
socket drop, and a call past 10 minutes.

### Commands

```bash
cd ak-py && ./build.sh && uv run pytest tests/test_realtime_pool.py tests/test_adk_realtime.py tests/test_livekit_gateway.py tests/test_ecs_akagentrunner_realtime.py -v
cd ak-py && uv run pytest
make lint-check-all
cd examples/api/livekit-voice/google/handoffs && ./build.sh local && uv run pytest -s
```

## Migration surface (docs and skills)

- `docs/docs/integrations/livekit.md`: tool callbacks and refusing a handoff, "Tokens for your users", "Talking into a live call", "Watching a live call"; new sections on the call's Live settings (`run_config`) and on recovery; the limitation at `:285` (pre- and post-hooks do not run on realtime turns; realtime observers see the call) and at `:288` (a Gemini socket failure no longer restarts the call)
- `docs/docs/integrations/hooks.md`: realtime mode runs no hooks; a pointer to realtime observers
- `livekit.md`: "Tools that wait for long work" (a separate session, cancellation, detecting a failed run natively), "Rooms per session" (a `GatewayRunner` per room), the call facts and `send_if_quiet`
- `realtime-internals.md`: tool calls that wait, the quiet rule and the guarded send
- `docs/docs/architecture/realtime-internals.md`: the adapter events, turn state as internal to the pool, the quiet rule, realtime observers, tool callbacks, a connection recovery section, the stall limit
- `core/realtime/runner.py`: the callback contract gains `reconnected` and the `reconnecting` status (Rule 2)
- `.agents/skills/ak-dev-architecture/SKILL.md`: a realtime section (it has none); `.agents/skills/ak-dev-testing-conventions/SKILL.md`: the `test_realtime_pool.py` row
- No new integration, so the docs-site landing and features pages are unchanged
- Bundled skills: no change (the one match, `ak-py/src/agentkernel/skills/ak-cloud-deploy/SKILL.md:561`, is about WebSocket async mode)
- `docs/versioned_docs/`: not edited

## Open items for review

- `RECONNECTED_NOTE` is prompt text inside an adapter; it is a class constant a subclass can change or empty
- The history ADK gives a new socket is unbounded; a long call sends every turn on a transfer or a restart
- ADK's transfer: the caller's words in its delay go to the agent handing over, and words said with a transfer reach the
  next agent only if Gemini marks their transcription finished; both are ADK's, not verified live
- ADK reads nothing from the socket while its tools run, so the caller's words during a long tool arrive after it
- The quiet delay, the reply wait, restart and stall thresholds come from one application's live runs
- Neither adapter acts on Gemini's `toolCallCancellation`; what Gemini does with the caller's speech while a blocking tool call is open is not verified live
- `send_if_quiet` is async only: its one consumer (the driving application's scheduler) runs on the realtime loop; a blocking variant can come with a caller that needs one
