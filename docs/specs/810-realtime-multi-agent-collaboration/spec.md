# #810: Realtime multi-agent collaboration with background work — Implementation Spec

Implements the requirements in [`design.md`](design.md). The realtime pool keeps each call's turn state, says
application posts at quiet moments through `RealtimeOutbox` / `RealtimeCall`, and feeds `RealtimeHook`s. The Gemini
adapter runs ADK's tool callbacks, seeds transfers with authored history, applies the call's `RunConfig`, and recovers
lost sockets by replaying the conversation. The
LiveKit gateway signs participant tokens. The idea: voice is the meeting room, not the engine.

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

## Design

### Package layout

```
ak-py/src/agentkernel/
├── livekit.py                 # NEW: public alias of integration.livekit
├── core/
│   ├── hooks.py               # RealtimeEvent, RealtimeHook
│   ├── base.py                # Agent.realtime_hooks
│   ├── module.py              # Module.realtime_hook
│   └── realtime/runner.py     # reports_speech_stopped; the new adapter events
├── framework/
│   ├── adk/adk.py             # GoogleADKRealtimeRunner; the ADK tool wrapper
│   └── openai/openai.py       # speech_stopped
├── integration/
│   └── livekit/adapter.py     # participant_token
└── pipeline/
    ├── __init__.py            # exports RealtimeCall
    └── realtime_pool.py       # turn state, RealtimeOutbox, RealtimeCall, hooks, recovery readiness, sweep
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

class RealtimeHook(ABC):
    async def on_event(self, session: Session, agent: Agent, event: RealtimeEvent) -> None: ...
    def name(self) -> str: ...

class Module:
    def realtime_hook(self, agent: Any, hooks: list[RealtimeHook]) -> Self: ...   # chains like pre_hook / post_hook

class RealtimeRunner:
    reports_speech_stopped: bool = False   # True only where the model signals the end of the caller's speech
```

Rules:

1. `core/hooks.py` imports nothing outside `core/` and pydantic.
2. The adapter callback contract (`RealtimeRunner` docstring) gains, none reaching the edge:
   - `speech_heard {}`: the caller is still speaking;
   - `speech_stopped {}`: the caller stopped; only from an adapter with `reports_speech_stopped`;
   - `caller_transcript {"text"}`: optional, the caller's words in one turn;
   - `reconnected {"agent", "seconds", "seeded"}`: the socket was replaced, with `seeded` true when the conversation was replayed;
   - `done` with status `reconnecting`: the turn under way ended because the socket was lost.
3. `Agent.realtime_hooks` is a list on the wrapped agent, like `pre_hooks`.
4. `set()` / `reset()` are unchanged for their callers, which activate once per run.

### ADK realtime runner (`GoogleADKRealtimeRunner`)

#### Tool callbacks

`execute_tool` runs `_run_tool(caller, tool, args, tool_context)`, `caller` being the agent that made the call:

1. Before-callbacks (`caller.canonical_before_tool_callbacks`) in order, each awaited when it returns an awaitable; stop at the first truthy result.
2. If the result is still `None`, run `tool.run_async`. If it raises, error callbacks in order until one returns non-`None`, which becomes the result; with none, re-raise.
3. After-callbacks in order with `tool_response`; stop at the first truthy result; a non-`None` one replaces the result.
4. Then read `tool_context.actions.transfer_to_agent`, as today.

The order matches ADK's (Verification); plugins do not run.

#### Caller turn events

- `_caller_turn_reported` is set when a caller turn is reported (`speech_started` or `interrupt`) and cleared when the model speaks or the turn completes
- A transcription of the caller (interim or final) while the model is silent reports `speech_started` once per turn, then `speech_heard` for each later one; while the model speaks, the existing barge-in rule applies
- The caller's words are reported as `caller_transcript` and logged (`Caller said: ...`) when the turn ends: `turn_complete`, a tool call, text sent in, a transfer or a lost socket

#### Authored history

- `_history` holds `_Said(author, content)`: `"user"` for the caller, else the agent's name
- `_presented_history()` builds a seed: caller entries as they are; agent entries through `_present_other_agent_message(Event(author=..., content=...))`
- A seed ends on the user's side, so it is sent with `turn_complete=True`, followed by `"."` on Gemini 3.x Live, as ADK does

#### Live settings

- `connect` reads `agent.run_options.get("run_config")` once; `_connect_config` sets, on every socket:
  - `realtime_input_config` from the `RunConfig`;
  - `input_audio_transcription` / `output_audio_transcription` from the `RunConfig`, else `AudioTranscriptionConfig()`.

#### Recovery

| Constant | Value | Meaning |
|---|---|---|
| `RECONNECT_ATTEMPTS` | 3 | Attempts per loss; also the quick drops in a row that give up |
| `RECONNECT_DELAYS_SECONDS` | (1, 2, 4) | Wait before each attempt |
| `RECONNECT_TIMEOUT_SECONDS` | 10 | Bound on one attempt's connect |
| `QUICK_DROP_SECONDS` | 20 | A socket lost this soon after a reconnect is a quick drop |
| `STALL_SECONDS` / `STALL_CHECK_SECONDS` | 15 / 1 | No model progress this long is a stall; checked this often |
| `HOLD_AUDIO_SECONDS` | 5 | Caller audio held while no socket is open |
| `SPEECH_LEVEL` | 500 | RMS of 16-bit samples above which held audio is speech |
| `RECONNECTED_NOTE` / `RECONNECTED_QUIET_NOTE` | text | The replay note when the caller spoke / did not; `""` adds none |

Triggers: `_listen` raising (a socket error, or the server closing the connection at its ~10 minute limit) and the
stall watchdog. Each calls
`_recover_soon(reason)`, which starts `_recover` unless one is running or the runner is closing.

`_recover(reason)`:

1. Set `_connection = None`, stop listening, close the socket.
2. Move the open socket's batches to `_lost_batches`; clear `_callers`, `_transfers` and the stall wait.
3. End the turn (report the caller's words), reset the turn flags, report `done {"status": "reconnecting"}`.
4. Count a quick drop when the last reconnect was under `QUICK_DROP_SECONDS` ago, else reset the count; at `RECONNECT_ATTEMPTS`, report `error` and stop.
5. For each attempt, after its delay (stop if closing):
   1. **Replay**: the note (`RECONNECTED_NOTE` when the caller was speaking at the loss or held audio has speech, else `RECONNECTED_QUIET_NOTE`), passed to `_open_socket(..., extra=[note])`, which adds it to that seed only. `_history` never holds a note.
   2. On success: listen, report `reconnected {"agent", "seconds", "seeded"}`, then send the held input.
6. When every attempt fails, report `error`.

Rules:

1. **Late tool results.** `send_tool_result` for a call in `_lost_batches` records the result; when its batch is complete, the calls and responses are appended to `_history` under the agent that made them, without ending the current turn, and nothing is sent to the socket. A transfer asked by a lost call is dropped.
2. **Stall wait.** `_owed_since` is set to now after a tool response, after text is sent, after a seed that completes a turn, and on each model audio or output transcription while a response is open; it is cleared on `turn_complete`, `interrupted` and a tool call. No other message touches it.
3. **Held input.** While `_connection` is `None` and the runner is not closing, `append_audio` keeps the latest `HOLD_AUDIO_SECONDS` and `send_text` queues the text; both go to the next socket after a reconnect or a transfer.
4. **Shutdown.** `disconnect()` cancels and awaits the watchdog and any recovery before closing the socket.

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
| `send_text(text, from_edge=True)` | `last_edge_text_at`; an `edge_text` hook event |

- `is_responding`: queued output, a tool in flight, or a response open with model output in the last `_UNFINISHED_RESPONSE_SECONDS` (15 s)
- `is_ready`: connected, not closed, not recovering
- `agent_has_spoken`: `last_model_generated_at` is later than `last_agent_change_at`

#### Outbox (`RealtimeOutbox`)

`QUIET_SECONDS = 1.5`, `REPLY_TIMEOUT_SECONDS = 15.0`, `MAX_PENDING = 20`; the pool's loop calls `_deliver_posts` every
`_POST_POLL_SECONDS = 0.25`.

`take(connection, now)`:

1. Drop expired posts; with none waiting, return `None`.
2. A new `connection` (not the last one posted into) owes nothing to earlier posts.
3. Return `None` while the connection is not ready, is responding, the caller is speaking, or a reply is owed: one of
   `last_caller_speech_at`, `last_edge_text_at`, `last_tool_result_at`, `last_reconnect_at` or the last post is later
   than `last_model_output_at` and younger than `REPLY_TIMEOUT_SECONDS`.
4. Return `None` until the newest of those times, `connected_at` and `last_model_output_at` is `QUIET_SECONDS` old.
5. Pop the first post, record the post time, return its text.

Rule: every write to the outbox's state (`_pending`, `_connection`, `_last_post_at`) is made under its lock, from
`quiet_for` as from `take`.

#### `RealtimeCall` and the pool's API

| `RealtimeCall` | Pool | Without a pool |
|---|---|---|
| `post_when_idle(text, key=None, expires_after=600.0) -> bool` | queues in the session's outbox; returns whether a call is connected | warning, `False` |
| `withdraw(key) -> bool` | drops a waiting post | `False` |
| `connected` | a ready connection exists | `False` |
| `quiet_for() -> float \| None` | seconds quiet, `None` while busy | `None` |
| `agent_has_spoken -> bool \| None` | as on the connection | `None` |
| `close() -> bool` | pops the connection and its outbox, closes it on the loop | `False` |

#### Hooks

- An agent with `realtime_hooks` gets an `asyncio.Queue` and one task per connection; `_observe` puts on the loop, `_observe_soon` from other threads
- Sources: `connect()` (`connected`); the pacing loop (`agent_changed`, `agent_said` at `done`, `interrupt` or a change); `caller_transcript` (`caller_said`); `send_text(from_edge=True)` (`edge_text`); `reconnected`; `close()` or a failure (`disconnected`, once)
- On close, the hooks get `_HOOK_DRAIN_SECONDS` (2 s), then the task is cancelled

#### Sweep and loop lag

- Every 5 s the loop pops and closes connections idle for `_IDLE_TIMEOUT_SECONDS` (300 s) **and** connections already closed by a failure
- The loop measures its own sleep; lag beyond `_LOOP_LAG_WARNING_SECONDS` (1 s) logs a warning

### LiveKit gateway (`LiveKitEdgeGateway`)

- `AGENT_IDENTITY_PREFIX = "agent-"`; agent identities are built from it
- `participant_token(identity, name=None, **grants)`: `ValueError` for an identity starting with the prefix, for `room` or `room_join` in `grants`, and with no key and secret; else `_sign(identity, name, **grants)`
- `_sign` builds `api.AccessToken(...).with_identity(...)`, adds the name when given, and grants `VideoGrants(room_join=True, room=self.session_id, **grants)`; `_mint_token` uses it with `can_update_own_metadata=True`

### Packaging

- `agentkernel/livekit.py` re-exports `integration.livekit`, as `slack.py` does
- No new extra; `ak-py/pyproject.toml` and `ak-py/uv.lock` unchanged

### Example (`examples/api/livekit-voice/google/handoffs/`)

| File | Change |
|---|---|
| `server.py` | `verify_account(account_id, tool_context)`, a supervisor tool, keeps a verified account in the ADK tool state, which lasts for the call across transfers; `require_account`, the supervisor's `before_tool_callback`, answers in place of `transfer_to_agent` to `billing` or `tech_support` until an account is verified; `book_technician` starts a short background job (a thread) that confirms the slot with `RealtimeCall(session_id).post_when_idle("[Dispatch] ...", key="dispatch")`, the session id read with `ToolContext.get()` inside the tool; a `CallLog(RealtimeHook)` logging `caller_said`, `agent_said`, `agent_changed` and `reconnected`, attached with `Module.realtime_hook(supervisor, ...)`; the gateway is built under `__main__` |
| `server_test.py` (new) | Offline tests (Testing) |
| `README.md` | Refusing a handoff, background updates, the call log, the walkthrough, tests; the transfer gap now holds the caller's words |

`.github/test-config.yaml`: `- type: api` / `path: examples/api/livekit-voice/google/handoffs`; the tests need no
model, LiveKit server or key.

### Consumer changes

- `RealtimeConnectionPool.dispatch`: text requests call `send_text(prompt, from_edge=True)`; the ECS realtime agent runner goes through `dispatch` (its test assertion changes)
- `RealtimeConnection.send_text` gains a keyword-only `from_edge=False`; other callers are unchanged
- LiveKit examples: public aliases; the `sqs` token handlers call `participant_token`

### Config changes

- No new fields, models, extras or env vars; existing YAML and `AK_*` variables are unaffected

### Behavioural changes

1. ADK realtime tool calls run the agent's tool callbacks. Intentional, the feature.
2. A lost or stalled Gemini socket reconnects the same agent instead of failing the call and restarting at the entry agent. Intentional.
3. Audio and text sent while no Gemini socket is open are held and sent to the next one, instead of dropped. Intentional.
4. A transfer's seed presents every agent's turn as user-side `[agent] ...` context, instead of model turns. Intentional, ADK's own presentation.
5. The ADK adapter reports `speech_started`, `speech_heard` and `caller_transcript`; the OpenAI adapter reports `speech_stopped`. None reaches the edge; `speech_started` is a barge-in only while paced audio is queued, as before.
6. The Live config takes turn detection and transcription from the call's `RunConfig`. Without a `run_config` option it is as before.
7. The pool's loop wakes every 0.25 s instead of 0.5 s; the idle sweep still runs every 5 s and now also closes failed connections.
8. LiveKit agent tokens are signed through `_sign`, with the same claims.

**Non-changes:** the stream event union and `AgentChanged`'s fields; queue message formats; OpenAI handoffs and the
LiveKit gateway's participants; `ToolContext.set()` / `reset()`; `AKConfig`; the extras; other examples' behaviour.

## Error handling

| Condition | Where | Surfaces as |
|---|---|---|
| Socket drops, server closes, stall | `GoogleADKRealtimeRunner._recover` | `done {"status": "reconnecting"}`, then `reconnected`; hooks get `reconnected` |
| Every reconnect attempt fails | `_recover` | `error` → the pool fails the connection; the edge gets an error chunk |
| Quick drops `RECONNECT_ATTEMPTS` times in a row | `_recover` | `error` ("keeps dropping") |
| A transfer's socket does not open in 15 s | `_transfer` | `error`, as before |
| A tool raises with no error callback answering | `_run_tool` → the pool | `Error: ...` as the tool result, as before |
| A tool result arrives for a lost socket | `send_tool_result` | recorded in the history; info log |
| A realtime hook raises | `_serve_hooks` | logged; the next hook runs |
| A hook is still busy at close | `_finish_hooks` | warning after 2 s; its task cancelled |
| `post_when_idle` with no pool in the process | `RealtimeCall` | warning; the post is dropped |
| A full outbox / an expired post | `RealtimeOutbox` | the oldest dropped with a warning / dropped with an info log |
| `participant_token` misuse | `LiveKitEdgeGateway` | `ValueError` |

## Testing

### Changed: `ak-py/tests/test_realtime_pool.py`

- `TestRealtimeTurnState`: each row of the turn-state table; a pause mid-answer; a lost `done`; readable from another thread; `is_ready` false between `reconnecting` and `reconnected`
- `TestADKRealtimeToolCallbacks`: before-callbacks stop a transfer, run in order, can ask for one; error and after-callbacks; async callbacks; the calling agent's callbacks
- `TestADKRealtimeSpeechStarted`, `TestADKCallerTranscript`, `TestOpenAIBargeIn`: the caller events of both adapters
- `TestADKRealtimeTransfers`: seeds as ADK presents them
- `TestADKConnectConfig`: the `RunConfig`'s turn detection and transcription on every socket
- `TestADKRealtimeRecovery`: replay with the right note; the note absent from the next seed; held audio and text; quick drops give up; every attempt failing fails; a late tool result in the next seed; stalls (a caller transcription keeps the wait; a response that stops mid-way recovers; an answering socket does not)
- `TestRealtimeOutbox`: quiet, busy, unready and recovering calls; owed replies, a seeded reconnect included; keys, withdrawal, expiry, overflow; a new connection
- `TestRealtimeCall`: posts with and without a call; `quiet_for`, `agent_has_spoken`; no pool; `close()` with and without a pool
- `TestRealtimeHooks`: events from connect to close, `reconnected` included; a failing hook; edge text from another thread; no hooks, no queue
- The pool: the sweep closes a failed connection without further input; the loop-lag warning
- `TestADKFirstAudioLog`: the wait logged once per turn

### Changed: other files

- `test_module.py`: `realtime_hook` attaches to the wrapped agent and chains
- `test_livekit_gateway.py`: participant tokens (room, grants, refusals, no key); the alias
- `test_ecs_akagentrunner_realtime.py`: `send_text(..., from_edge=True)`

### New: `examples/api/livekit-voice/google/handoffs/server_test.py`

- `require_account` answers in place of a transfer to a specialist until the account is verified, then lets it through; other tools and other transfers pass
- `verify_account` records a verified account in the tool state and refuses a malformed one
- `book_technician` posts the confirmation once its job ends (a fake `RealtimeCall`), keyed `dispatch`
- `require_account` is the supervisor's callback, and `CallLog` its realtime hook; `CallLog` logs both sides of the call

### Live check

On `gemini-3.1-flash-live-preview`, with background agents on `openai/gpt-4.1` through LiteLLM: a handoff refused by a
callback, a background post said at a quiet moment, a forced socket drop, and a call past 10 minutes.

### Commands

```bash
cd ak-py && ./build.sh && uv run pytest tests/test_realtime_pool.py tests/test_module.py tests/test_livekit_gateway.py tests/test_ecs_akagentrunner_realtime.py -v
cd ak-py && uv run pytest
make lint-check-all
cd examples/api/livekit-voice/google/handoffs && ./build.sh local && uv run pytest -s
```

## Migration surface (docs and skills)

- `docs/docs/integrations/livekit.md`: tool callbacks and refusing a handoff, "Tokens for your users", "Talking into a live call", "Watching a live call"; new sections on the call's Live settings (`run_config`) and on recovery; the limitation at `:285` (pre- and post-hooks do not run on realtime turns, realtime hooks do) and at `:288` (a Gemini socket failure no longer restarts the call)
- `docs/docs/integrations/hooks.md`: `RealtimeHook`
- `docs/docs/architecture/realtime-internals.md`: the adapter events, turn state as internal to the pool, `RealtimeOutbox`, realtime hooks, tool callbacks, a connection recovery section, the stall limit
- `core/realtime/runner.py`: the callback contract gains `reconnected` and the `reconnecting` status (Rule 2)
- `.agents/skills/ak-dev-architecture/SKILL.md`: a realtime section (it has none); `.agents/skills/ak-dev-testing-conventions/SKILL.md`: the `test_realtime_pool.py` row
- No new integration, so the docs-site landing and features pages are unchanged
- Bundled skills: no change (the one match, `ak-py/src/agentkernel/skills/ak-cloud-deploy/SKILL.md:561`, is about WebSocket async mode)
- `docs/versioned_docs/`: not edited

## Open items for review

- `RECONNECTED_NOTE` is prompt text inside an adapter; it is a class constant a subclass can change or empty
- The replayed history is unbounded; a long call sends every turn on a transfer or a replayed reconnect
- The outbox, reconnect and stall thresholds come from one application's live runs
