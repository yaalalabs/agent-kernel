# #810: Native realtime agents and handoffs — Implementation Spec

This specifies how to build the [design](design.md). OpenAI Agents SDK and Google ADK own live model sessions, agent turns, handoffs, and tool execution. Agent Kernel (AK) owns the queue and LiveKit edge. For example, a billing agent can hand a call back to a coordinator using its SDK's handoff feature; AK only changes which LiveKit participant speaks.

## Design

### Boundary and existing architecture

1. Keep the existing `Agent.realtime_runner_cls` selection point (`ak-py/src/agentkernel/core/base.py:560`) and `RealtimeRunner` ABC (`ak-py/src/agentkernel/core/realtime/runner.py:17`). This is already the pluggable class seam for built-in and bring-your-own runners. Do not add a second provider factory or import either SDK from `core/`.
2. Keep `RealtimeConnection` and `RealtimeConnectionPool` (`ak-py/src/agentkernel/pipeline/realtime_pool.py:39`, `:321`): one connection per AK session ID, one pool event loop, queue transport, 24 kHz edge PCM, input conversion, ordered output, pacing, barge-in, idle eviction, and shutdown. Framework SDKs have no responsibility for this AK/LiveKit boundary.
3. Keep the `StreamChunk` and `AgentChanged` queue shape and LiveKit participant selection (`ak-py/src/agentkernel/integration/livekit/adapter.py:331`, `:385`, `:463`). Never send agent participant audio or chat back to a model as caller input (`adapter.py:235`, `:252`). One native framework conversation serves the room; only its active speaker is unmuted. Handoff A → B → A stays inside that conversation, with no audio loop between agents.
4. ADK 2.9.0 offers an [experimental `LiveKitRunner`](https://adk.dev/integrations/livekit/) that handles media for a documented single ADK participant. Evaluate it against AK's existing queue routing and separate participant per speaking agent before treating it as a replacement. This spec keeps the shared AK edge because those contracts are not established by the documented native runner; it does not add a parallel ADK-only LiveKit path.

### `RealtimeRunner` contract

Change `ak-py/src/agentkernel/core/realtime/runner.py` to this lifecycle shape (typing abbreviated):

```python
class RealtimeRunner(Runner):
    input_sample_rate: int = EDGE_SAMPLE_RATE
    output_sample_rate: int = EDGE_SAMPLE_RATE

    def team(self, agent: Agent) -> list[str]: ...
    def initial_speaker(self, agent: Agent) -> str | None: ...  # default agent.name
    async def connect(self, session: Session, agent: Agent, callback: Callable) -> None: ...
    async def append_audio(self, base64_audio: str) -> None: ...
    async def send_text(self, text: str) -> None: ...
    async def disconnect(self) -> None: ...
```

- Delete `execute_tool()` and `send_tool_result()` from the ABC. Delete `tool_call` from its callback contract. The only callback event names are `audio_delta`, `transcript_delta`, `agent_changed`, `interrupt`, `speech_started`, `done`, and `error`. An event has the current dictionary payload shape documented by the ABC; audio is base64 PCM16 at `output_sample_rate` with `message_id`.
- Do not add a queue-delivery callback to the ABC for playback tracking. A queue send is earlier than actual LiveKit playout, so it must not advance the SDK tracker. Use the SDK's default playback estimate until a reliable edge playout signal is available; document that estimate and test interruptions.
- `team()` returns a stable list of known speaking-agent names, without constructing a new graph. A default `initial_speaker(agent)` returns `agent.name`; an adapter with a non-speaking root may return `None`. The pool enqueues the initial `AgentChanged` only when there is an initial speaker. Subsequent adapter `agent_changed` events use the same FIFO pacing queue. The adapter must emit a change before the new speaker's audio or transcript. A name discovered after connection may extend the roster in that change event.
- All adapter state belongs to the runner instance created for one connection. The callback is awaited in native event order. `disconnect()` is idempotent. Startup that fails after opening SDK resources closes them before raising. Background listeners report unexpected failure through `error` and never report normal `disconnect()` as an error.

### Realtime pool

In `ak-py/src/agentkernel/pipeline/realtime_pool.py`:

- Remove `_execute_tool_and_reply()` and all imports used only by that path. `handle_framework_event("tool_call", ...)` must call `_fail()` with a message naming the removed contract, close/evict the connection, and never execute the tool. Unknown event names must likewise fail with the event name instead of being ignored. These failures become terminal error chunks through the existing queue path.
- Preserve `_interrupt()` semantics: discard audio and transcript still in the pacing queue, keep queued control events, and send `Interrupt`. Do not decide an SDK handoff or call a tool here.
- On failed `connect()` or its 15-second `get_or_create()` wait, remove only that connection's registry entry, cancel its pending connect future if needed, and await/arrange `conn.close()` on the pool loop. Do not remove a replacement connection inserted concurrently. Preserve the 10-second send bound, 5-minute idle eviction, and 2-second shutdown grace unless a focused test proves a change necessary (`realtime_pool.py:20-27`, `:462`).
- The registry lock protects connection creation and eviction, not SDK calls. Input from consumer threads reaches the single pool loop through `run_coroutine_threadsafe`. A second AK session has a separate runner, SDK session, and ADK queue.

### OpenAI adapter

Replace `OpenAIRealtimeRunner` in `ak-py/src/agentkernel/framework/openai/openai.py:627` with a thin owner of one native `agents.realtime.RealtimeRunner` and `RealtimeSession`. Remove raw `AsyncOpenAI` socket handling, `_activate`, `_offered_tools`, `_offered_handoffs`, `_switch_to`, manual JSON tool replies, custom transcript replay, and manual reconnection. Do not copy or mutate the native agent graph to wrap tools.

1. Require the wrapped native root to be `RealtimeAgent`. `OpenAIModule` may still load ordinary `agents.Agent` for unary use; selecting it for realtime raises `TypeError` before opening a socket. The native realtime graph uses `RealtimeAgent.handoffs`, including SDK `realtime_handoff(...)` objects. Walk only public graph fields for the optional roster; if a dynamic handoff cannot be listed early, announce it when its SDK event arrives. Do not substitute regular `agents.handoff` or an AK routing tool.
2. Resolve `Module.run_options` once at connection start with `agent.resolve_run_options(session, [])`. Accept only options that map to the native `RealtimeRunner(config=...)` and `run(model_config=...)`/`run(context=...)` call; reject unknown or reserved keys with agent name and key. The SDK's model and audio settings remain native objects/dicts. The example must show where the OpenAI model and one session voice are set; `RealtimeAgent` itself has no per-agent model or voice.
3. Enter the native session and consume its async event stream in one listener task. `append_audio()` base64-decodes to bytes and calls `session.send_audio()`. `send_text()` calls `session.send_message()`. The SDK owns tool execution, handoffs, approval state, history, guardrails, and model transport. The adapter never handles a raw tool call.
4. Map high-level `audio` to `audio_delta` using `event.audio.data`. Map the public `raw_model_event` payload types `RealtimeModelTranscriptDeltaEvent` and `RealtimeModelOutputTextDeltaEvent` to `transcript_delta`, and `RealtimeModelTurnEndedEvent` to `done`. Map high-level `audio_interrupted` to `interrupt`, `handoff`/a changed `agent_start` to `agent_changed`, and native failure to `error`. Do not map `agent_end` alone to a speaker change. Deduplicate `handoff` and following `agent_start` for the same speaker. Preserve ordering before that speaker's first content. Treat clean end of native iteration as connection closure; it is not a fresh turn.
5. Keep the SDK's default interruption/playback estimate. `RealtimePlaybackTracker.on_play_bytes()` means bytes actually played to the listener, so do not call it from the AK output queue. If the LiveKit edge later exposes reliable playout progress, pass that signal to the SDK tracker as a separate change. Record the current estimate's effect during barge-in tests.
6. An OpenAI `tool_approval_required` event needs a human decision. LiveKit has no approval response route in this design, so do not auto-approve. Reject statically declared approval tools at connect when the public tool definition exposes `needs_approval`; if a dynamic approval event still occurs, call the SDK's `reject_tool_call(call_id)` and fail the AK connection with a clear unsupported-approval error. Keep supported SDK output and tool input guardrails in native execution; `guardrail_tripped` must clear buffered output through the SDK interruption event or an immediate AK `interrupt`, then allow the SDK's own recovery response to continue. Do not silently drop a guardrail or approval tool.
7. Native MCP servers/tools on `RealtimeAgent` stay attached to the native agent. Their actual use must be verified in the installed SDK; if the chosen SDK/model rejects one, surface that native error. AK does not implement an MCP executor. Native resumption or reconnect settings, if the SDK exposes them, are passed through; AK never promises restoration of the LiveKit call after process restart.

The exact event attributes must be confirmed against the pinned `openai-agents` version while implementing; use the SDK's public event types, not raw provider JSON. Current optional extra is `openai-agents>=0.20.0,<0.21` (`ak-py/pyproject.toml:118`). If a required public event is absent at that floor, raise the floor to the first verified version and update example lockfiles in the same iteration. Do not write a private-SDK workaround.

### ADK adapter

Replace `GoogleADKRealtimeRunner` in `ak-py/src/agentkernel/framework/adk/adk.py:918` with one native `google.adk.runners.Runner.run_live()` async generator and one `LiveRequestQueue` per AK connection. Remove `BidiGenerateContent` socket creation, copied transfer instructions, tool declarations/results, `_batches`, `_transfers`, `_history`, replay, manual connection switching, and custom SDK retry logic. Preserve the native `BaseAgent` tree or `Workflow` relationships; do not clone the graph.

1. Reuse `GoogleADKSession`'s session service and AK session ID from the unary adapter (`adk.py:279`, `:361`) rather than creating an unrelated store. Create the ADK session before `run_live()`. Use one `App(root_agent=agent.agent, ...)` and ADK `Runner` with the same owned app/session-service pattern. Start consuming `run_live(user_id=..., session_id=..., live_request_queue=..., run_config=...)` before accepting input. The listener owns the generator's lifetime; close queue, generator, and runner resources on stop or startup failure. ADK's graph `Workflow` root is a `BaseNode`, not a `BaseAgent`; widen only the AK wrapper's live root acceptance needed for this native type.
2. `append_audio()` decodes the pool's 16 kHz PCM16 and sends an ADK `types.Blob` through `LiveRequestQueue.send_realtime()`. `send_text()` sends a user `types.Content` through `send_content()`. Do not call Gemini Live directly. Set `input_sample_rate=16000`; output PCM rate comes from ADK's actual live output format and is declared on the adapter for pool resampling.
3. Use each ADK `Event.author` when the event represents a speaking agent. Emit `agent_changed` before the first audio/text of a newly active author. Ignore tool authors and framework/control events for speaker selection. Map output audio, output transcription/text, interruption, completion, and failure into the ABC callback events. One `LiveRequestQueue` continues across native transfers, including A → B → A; ADK, not AK, opens any next Gemini session.
4. Validate known unsupported live graph shapes before starting: `ParallelAgent` and `LoopAgent` anywhere on the live route; speaking `Workflow` nodes left in `single_turn` instead of `chat` or `task`; unsupported native root/model combinations. For a non-speaking `Workflow` root, `initial_speaker()` returns `None`; defer its first speaker announcement until ADK identifies the first speaking author, then send the declared roster with that change. Do not publish the workflow container as a voice participant. For a normal speaking root, the pool's initial change names it; the BYO default remains `agent.name`.
5. `Module.run_options` accepts native ADK `Runner` constructor options already split by `GoogleADKRunner._split_run_options()` (`adk.py:240`) and a native `run_config` for `run_live()`. Reject keys used internally (`session`, `session_id`, `user_id`, `live_request_queue`, root `agent`/`app`, and session service) instead of allowing a duplicate argument. Do not synthesize a `RunConfig` for each native setting AK does not own. Use `Gemini(speech_config=...)` for per-agent voice or `RunConfig.speech_config` for a shared voice; the old `generate_content_config.speech_config` path is not read by `run_live()`.
6. Keep native ADK tools and toolsets attached. ADK executes them and emits their results. A tool requiring confirmation cannot receive a LiveKit decision here: reject static confirmation declarations when public metadata makes them identifiable. At runtime, detect a confirmation request in the public `Event.actions.requested_tool_confirmations` field, fail the AK connection, and close the live run. ADK's live tool flow refuses such a call itself; AK must not try to resume or approve it. Never answer yes automatically or leave a pending confirmation hidden. Confirm the event path against ADK 2.7.0 before shipping; do not inspect private SDK fields to guess. Native plugins/guardrails are passed to ADK when supported by `run_live`; a declared unsupported option fails at connect. Native session resumption is optional and covers ADK ↔ Gemini only.

Raise the optional `google-adk` floor from `>=1.24.0` to `>=2.7.0` in `ak-py/pyproject.toml:123`, which includes the live transfer ordering fix. In a minimum-version test environment, measure what happens when `transfer_to_agent` is refused or invalid; do not assume the call remains usable. Update lockfiles of edited ADK examples. The [ADK live workflow guide](https://adk.dev/live/workflows/) documents one queue, per-author output, and the unsupported legacy loop/parallel agents; [live configuration](https://adk.dev/live/configuration/) documents voice placement.

### Scope: native features only

Realtime runs native agent features only. AK hooks and AK guardrails are not part of the native live path. When `execution.mode` is `realtime`, the OpenAI and ADK agent wrappers do not call `Agent._attach_system_tools()` or `Agent._setup_system_prompt()`, so AK system tools (multimodal, sandbox, schedule, knowledge base) and their guidance are absent. Other modes keep their existing behavior. Native tools declared on the SDK agents run through the SDK.

### First-release support list

| Capability | OpenAI live adapter | ADK live adapter |
| --- | --- | --- |
| Agent handoffs and agent-specific native tools | Native `RealtimeAgent` session | Native `run_live()` / `LiveRequestQueue` |
| Native MCP tools or toolsets | Pass `RealtimeAgent.mcp_servers` through; test SDK/model acceptance | Pass native ADK toolsets through; test SDK/model acceptance |
| Approval or confirmation | Reject: LiveKit has no decision route | Reject: LiveKit has no decision route |
| Guardrails | Native realtime output/tool-input guardrails; map interruption | Native live plugins/callbacks where ADK runs them; reject unsupported declarations |
| AK hooks and AK guardrails | Not automatically invoked by the native live runner | Not automatically invoked by the native live runner |
| AK system tools | Not part of the live path | Not part of the live path |
| Native connection recovery | Follow SDK behavior; no AK replay | ADK session resumption if configured; no AK replay |
| LiveKit call after process restart | Unsupported | Unsupported |

The implementation tests each “pass through” case. If a native SDK rejects it, expose that error and document the tested limit; do not add an AK substitute.

### Consumer changes

- `OpenAIModule`/`OpenAIAgent` (`openai.py:1023`, `:1094`) keep unary `Agent` support. The realtime path accepts `RealtimeAgent`; its wrapper must avoid assumptions specific to ordinary `Agent` when reading instructions. `OpenAIToolBuilder.bind()` remains a native `function_tool` binder for callers that choose it; the realtime runner no longer rebinds its output.
- `GoogleADKModule`/`GoogleADKAgent` (`adk.py:1456`, `:1527`) keep native agent wrapping and unary behavior. The live path also accepts ADK's graph `Workflow` root. The realtime runner does not call `GoogleADKToolBuilder._wrap()` itself or replace ADK toolsets with function declarations.
- `RealtimeConnectionPool` and the queue consumer keep their existing transport and AK session IDs. LiveKit keeps room participants, muting, and input filtering; only speaker events from native SDKs change the selected participant.
- Migrate `examples/api/livekit-voice/openai/{in_memory,handoffs}` and any other OpenAI realtime sample that builds ordinary `Agent` to `RealtimeAgent`. Migrate ADK samples' per-agent voice to native `Gemini(speech_config=...)`; remove documentation of manual transfer/tool limits that no longer apply. Update `docs/docs/architecture/realtime-internals.md`, `docs/docs/integrations/livekit.md`, and relevant example READMEs with a per-SDK capability table.

### Config changes

- No new `AKConfig` field. `execution.realtime.playback_lead_ms` (default 50) and `input_batch_ms` (default 100) remain the edge controls (`ak-py/src/agentkernel/core/config.py:668-712`). Queue and LiveKit settings stay as they are. Existing YAML and `AK_*` variables keep parsing the same way. Existing data in AK session stores and output queues keeps its layout.
- `Module.run_options` remains the per-agent native option seam (`core/module.py:101`). The realtime runner resolves it once per connection, not once per audio frame. A chosen SDK option must have a named destination as described above; bad options fail before any native call. No new `enabled`, tool, handoff, or reconnect flag is introduced.
- Native SDK settings may require **application code migration**: OpenAI model/voice move from ordinary `Agent` fields into realtime runner/session configuration; ADK per-agent voice moves from `generate_content_config.speech_config` into `Gemini(speech_config=...)`. Document exact before/after examples. OpenAI's one-session voice cannot switch after speech begins.

### Behavioural changes

1. **Intentional:** OpenAI realtime requires `RealtimeAgent`; ordinary OpenAI `Agent` now fails at live connect. Unary OpenAI runs remain valid.
2. **Intentional:** OpenAI and ADK native SDKs execute their own tools and handoffs. The pool no longer handles a `tool_call`; BYO runners emitting it fail loudly.
3. **Intentional:** The OpenAI and ADK wrappers skip AK system tools and their guidance in realtime mode. Unary and stream modes continue to use them.
4. **Intentional:** Approval-requiring tools cannot proceed through LiveKit without a decision route. A declared approval fails preflight where detectable; a runtime request is rejected and surfaced. No implicit approval.
5. **Intentional:** ADK live transfers may open a new Gemini connection under ADK, while the AK/LiveKit room and one ADK `run_live()` call remain active. No AK transcript replay.
6. **Intentional:** ADK 2.7.0 becomes the minimum extra version. Its native transfer behavior replaces AK's prior emulation.
7. **Intentional:** Per-agent ADK voice uses native `Gemini`; OpenAI uses one session voice. Existing voice declarations in the old location need migration.
8. **Intentional:** Native SDK guardrail, MCP, and reconnection behavior is accepted only where the selected SDK and AK edge actually carry it. AK hooks and AK guardrails are not automatically part of this live path and must be documented as such. An unsupported native declaration or event is an explicit error, never a quiet omission.

**Non-changes:** AK queue envelope and `StreamChunk` data format; session ID routing; `AgentChanged`/`AudioDelta`/`TextDelta`/`Interrupt` public event names; `realtime_runner_cls` constructor seam; existing `execution.realtime` fields and defaults; LiveKit room participant filtering; unary/stream runner APIs. This does not add simultaneous model speech, automatic group discussion, or process-restart recovery.

## Error handling

- **Preflight:** reject a known invalid native agent/graph, unsupported approval, or bad run option with `TypeError`/`ValueError` naming the agent, option/tool, and remedy. Missing optional SDK import follows the adapter's existing optional-extra error convention. Detect these before SDK connection where public declarations allow it; close any partial session for errors detected later.
- **Startup:** let SDK `Exception` failures propagate to `get_or_create()` after closing partially created native session/queue/listener. `asyncio.CancelledError` is handled separately for cancellation and re-raised after cleanup. A connect timeout cancels the pending future and schedules idempotent close. Never catch `BaseException` broadly.
- **Active session:** unexpected SDK event/listener/send failure becomes one terminal error chunk via `_fail()`, marks the connection closed, and evicts it on the next lookup. No automatic replay or AK-side reconnect loop. A later caller input may start a new native session in the same AK process; prior native conversation state is not promised after failure.
- **Clean close:** queue/SDK session close, listener cancellation, pacing stop, and transport cleanup are idempotent. A normal shutdown emits no spurious error. Closing one AK session cannot close another's SDK resources.
- **Delivery:** an output-queue failure follows the existing queue error path. Native guardrail interruption drops queued audio promptly. LiveKit playout acknowledgement is not available, so the SDK's default playback estimate is approximate; no code should report a queue send as played audio.

## Testing

Use SDK fakes or public mock sessions for unit tests; reserve credentialed smoke tests for an opt-in environment. Test the published AK event/queue contract, not private SDK internals.

| File | Required checks / patch targets |
| --- | --- |
| `ak-py/tests/test_realtime_pool.py` | Update `_Adapter` to the reduced ABC; replace `TestFrameworkToolExecution` with `tool_call`/unknown-event terminal failure; verify output ordering, resampling, pacing, interrupted queued audio removal, startup cleanup, two-session isolation, and no changes to batching/eviction. Patch `QueueTransportFactory.create` / the fake adapter, not an SDK socket. |
| `ak-py/tests/test_openai_runner.py` or a focused `test_openai_realtime.py` | Patch the native `RealtimeRunner` and `RealtimeSession` objects imported by `agentkernel.framework.openai.openai`. Test native A → B → A handoff with each agent's own tool executed by the fake SDK, `AgentChanged` before each speaker's content, text/audio/interrupt/done/error mapping, the SDK's default interruption estimate, unsupported ordinary `Agent`, approval refusal, guardrail interruption, MCP pass-through/error, and close. Assert no direct raw socket/tool-result calls or false tracker updates from queue delivery. |
| `ak-py/tests/test_adk_runner.py` or a focused `test_adk_realtime.py` | Patch native `Runner.run_live` and `LiveRequestQueue` at `agentkernel.framework.adk.adk`. Test one queue for A → B → A, native tool events without pool execution, author-to-speaker mapping, audio/text input, `RunConfig` and voice, unsupported graph modes, confirmation failure, failed startup cleanup, and per-session separation. Run refused transfer against `google-adk==2.7.0` in an optional SDK integration test. |
| `ak-py/tests/test_livekit_gateway.py` | Verify starting roster, native speaker changes, mute order and edge audio/text attribution; own agent participant audio/chat stay excluded. Cover an ADK workflow root whose first speaking author differs from its container name. |
| `ak-py/tests/test_ecs_akagentrunner_realtime.py` | Keep queue consumer routing tests; verify the pool still creates one connection per session and reports a native startup failure without acking it as success. |

Run focused tests from `ak-py/` with `uv run pytest tests/test_realtime_pool.py tests/test_openai_runner.py tests/test_adk_runner.py tests/test_livekit_gateway.py tests/test_ecs_akagentrunner_realtime.py`; run `make lint-check-all` from the repo root before implementation is considered complete. Credentialed live-call tests require API keys and are a separate verification gate, not a reason to skip the deterministic tests. Record the installed SDK versions used for the SDK integration checks.


## Edge additions for realtime meetings (C1 to C6)

The full detail of the six additions (the caller's words as an event, edge hooks and live captions, gateways at runtime, ending a session at once, the opening prompt, reconnect back-off). The use case that needs them is specified in its own folder.

### 1. The caller's words as an event (C1)

#### 1.1 `InputTranscript` (`ak-py/src/agentkernel/core/event.py`)

```python
class InputTranscript(StreamEventBase):
    """One finished utterance of the caller in a realtime conversation, as text.

    Ordered with the output around it, so a transcript built from the stream reads in spoken order.
    Reported only when the framework's own input transcription is on; an edge that does not show a
    transcript ignores it.
    """

    type: Literal["input_transcript"] = "input_transcript"
    message_id: str   # the framework's item/event id, or uuid4().hex when it has none
    content: str      # the finished text; never empty
```

- Added to the `StreamEvent` union, right after `AgentChanged` (`core/event.py:254`).
- It is not projected into `StreamChunk.delta`. `delta` stays assistant prose only (`core/model.py:346`).

#### 1.2 The `RealtimeRunner` contract (`ak-py/src/agentkernel/core/realtime/runner.py`)

- The `connect()` docstring's event list (`runner.py:104-121`) gains one entry:
  - `input_transcript`: `{"text": str, "message_id": str}`. One finished caller utterance; report it only when the
    text is not empty, and never report partial text.
- The abstract methods do not change. A bring-your-own runner that never reports the event keeps working.

#### 1.3 The realtime pool (`ak-py/src/agentkernel/pipeline/realtime_pool.py`)

- **`handle_framework_event`** (`:108`) puts `input_transcript` on `_audio_queue`, as it does `done` and
  `agent_changed` (`:140`). An unknown event still fails the connection.
- **`_interrupt`** (`:152`) keeps a queued `input_transcript` with the control events. It is the caller's words, not
  agent output the caller will no longer hear.
- **`_pacing_loop`** (`:196`) emits `StreamChunk(event=InputTranscript(message_id=..., content=data["text"]))`. Like a
  `transcript_delta`, it does not reset the pacing window.

**Rules:**

1. **The order is "behind queued output", which settles the design's open question.** The caller's line rides
   `_audio_queue`, so it reaches the edge after any agent output the caller has already heard.
   - In practice the queue is empty by then. A barge-in clears it (`_interrupt`). Transcription finishes only after
     the caller stops speaking, and a `speech_started` with audio still queued is itself a barge-in (`:137`).
   - So the delay is at most the playback lead (`execution.realtime.playback_lead_ms`).
2. `_queued_audio` counts audio only. It is unchanged by this event.

#### 1.4 ADK adapter (`ak-py/src/agentkernel/framework/adk/adk.py`)

In `GoogleADKRealtimeRunner._handle_event`, the early return for `event.author == "user"` (`:1112`) becomes:

```python
if event.author == "user":
    transcription = event.input_transcription
    if transcription is not None and transcription.finished and (transcription.text or "").strip():
        await self._callback("input_transcript", {"text": transcription.text.strip(), "message_id": event.id})
    return False
```

- ADK labels transcribed caller speech with `author == "user"` (`google/adk/flows/llm_flows/base_llm_flow.py:1130`).
  It sends partial pieces and then one finished aggregate (`google/adk/models/gemini_llm_connection.py:465`), so only
  the finished one is reported.
- A user-authored event with `content` and no `input_transcription` (history replayed into a new agent at a transfer)
  is not reported. It is not new speech.
- **No setting is needed.** `RunConfig.input_audio_transcription` defaults to on (`google/adk/agents/run_config.py:127`).

#### 1.5 OpenAI adapter (`ak-py/src/agentkernel/framework/openai/openai.py`)

In `OpenAIRealtimeRunner._handle_model_event` (`:805`), add one branch:

```python
elif kind == "input_audio_transcription_completed":
    text = (data.transcript or "").strip()
    if text:
        await self._callback("input_transcript", {"text": text, "message_id": data.item_id})
```

- The SDK forwards each model event as a `raw_model_event` (`agents/realtime/session.py:405`). The event type is
  `RealtimeModelInputAudioTranscriptionCompletedEvent` (`agents/realtime/model_events.py:78`).
- **It needs a setting:** `input_audio_transcription` in the session's model settings (`agents/realtime/config.py:220`).
  An app passes it through `Module.run_options(..., model_config={"initial_model_settings": {...}})`. AK adds no
  default.

### 2. Edge hooks and live captions (C2)

#### 2.1 `TranscriptLine` and the hooks (`ak-py/src/agentkernel/integration/adapter/base.py`)

```python
class TranscriptLine(BaseModel):
    """One finished line of a realtime conversation, as an edge assembled it."""

    speaker: str                         # agent name, or the caller's participant identity
    role: Literal["user", "agent"]
    text: str
    at: float                            # epoch seconds when the line finished at the edge
    message_id: Optional[str] = None
    interrupted: bool = False            # an agent line cut off by the caller: the text is what was delivered
    typed: bool = False                  # a user line the caller typed in the room chat instead of speaking


class StatefulEdgeAdapter(ABC):
    ...
    # ── Observation hooks: override in an app subclass; each runs on the edge's hook worker ──
    def on_transcript(self, line: TranscriptLine) -> None: ...
    def on_agent_changed(self, agent: str, previous: Optional[str]) -> None: ...
    def on_error(self, message: str) -> None: ...

    def _dispatch_hook(self, hook: Callable[..., None], *args: Any) -> None:
        """Queue one hook call on this edge's hook worker, in call order; never blocks the caller."""

    def _close_hooks(self, wait: bool = True) -> None:
        """Stop the hook worker after the calls already queued; safe to call more than once."""
```

- `TranscriptLine` is exported lazily from `agentkernel.integration.adapter`, beside `StatefulEdgeAdapter`
  (`integration/adapter/__init__.py:15`).
- **The hook worker** is a private class, `_EdgeHookWorker`, in `base.py`. It wraps one
  `concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="edge-hooks-<session_id>")`:
  - It is created lazily, on the first dispatch, so an edge that never calls a hook starts no thread.
  - `submit()` wraps each call in a guard that logs an exception at ERROR (`ak.integration.edge_hooks`) and swallows
    it.
  - After `close()`, `submit()` drops the call with a DEBUG log.
- `StatefulEdgeAdapter.__init__` sets `self._hooks = None`. Existing subclasses already call `super().__init__()`, as
  `LiveKitEdgeGateway.__init__` does (`livekit/adapter.py:108`).

**Rules:**

1. **Hooks never run on the delivery thread.** `deliver_chunk` runs on the Response Handler's thread
   (`pipeline/response_handler.py:172`), which serves every edge in the process. A slow hook on it would delay audio
   for all of them.
2. **One worker per edge keeps order.** Calls run in the order the edge dispatched them, which is output-queue order
   for that session.
3. **Hooks are plain methods** (not `async`). An app hook may block, for example on a file write, without touching any
   event loop.
4. **An app's hook is called from the worker thread.** Any state it shares with other threads needs its own lock. The
   use case's `MeetingLog` has one (section 6.2).

#### 2.2 Lines in the LiveKit gateway (`ak-py/src/agentkernel/integration/livekit/adapter.py`)

The gateway keeps a line buffer, `_line_parts: list[str]`, separate from the chat buffer `_transcript` (`:373`). The
chat buffer is not split at handoffs on a single-participant gateway (`_change_speaker` returns early, `:406`), but
a line must always be.

`deliver_chunk` (`:340`) changes as follows:

| Chunk | Today | Added |
|---|---|---|
| `text_delta` | appended to `_transcript` | also appended to `_line_parts`, unless the turn was interrupted; written to the agent caption (2.3) |
| `agent_changed` | team join, then `_change_speaker` | **first**, flush the line of the agent that was speaking, then dispatch `on_agent_changed(agent, previous)` |
| `interrupt` | `_interrupted = True`, clear playback | flush the line with `interrupted=True`; drop text deltas until `done` |
| `input_transcript` | (new) | dispatch `on_transcript` with a `user` line; publish the caller caption (2.3) |
| `done` | publish chat text | flush the line, unless it was already flushed at the interrupt |
| error chunk | clear, then `deliver_error` | flush the partial line with `interrupted=True`, then dispatch `on_error(chunk.error)` |

- **Flushing** joins `_line_parts`. If the text is not empty, it dispatches `on_transcript(TranscriptLine(...))` with:
  - `role="agent"`;
  - `speaker` = `_speaking_agent`, else `self.agent`, else `"agent"`;
  - the last `message_id` seen.

  Then it clears the buffer.
- **`previous`** for `on_agent_changed` is `event.previous_agent`, falling back to the `_speaking_agent` from before
  the change.
- **The caller's identity and track:** `_on_track_subscribed` (`:244`) records `self._caller_identity` and
  `self._caller_track_sid`. The `user` line's `speaker` is that identity, or `"user"` before any track has been seen.
- **`deliver_error`** called directly (the permanent-failure path, `response_handler.py:208`) also dispatches
  `on_error(message)`.
- **Typed chat is a caller line.** `_handle_chat_message` (`:353`) stages the `AgentRequestText` as before. After
  staging, it dispatches `on_transcript(TranscriptLine(speaker=<the sender's identity>, role="user", text=text,
  at=time.time(), typed=True))` through `_dispatch_hook`. Without it, a typed message reached the model but never the
  transcript, so a server reading the hooks (the scribe) never saw it: in the live test the typed goal and scope never
  reached the board. A message from an agent participant (its published transcript) is still ignored and gives no line.

#### 2.3 Live captions in the LiveKit gateway

Captions follow LiveKit's transcription conventions ([docs](https://docs.livekit.io/agents/build/text/)), held as
class constants:

```python
TRANSCRIPTION_TOPIC = "lk.transcription"
ATTR_TRANSCRIBED_TRACK = "lk.transcribed_track_id"
ATTR_SEGMENT = "lk.segment_id"
ATTR_FINAL = "lk.transcription_final"
```

A private class, `_CaptionSegment`, owns one segment. A segment is one agent's text between two boundaries: `done`,
`agent_changed`, `interrupt`, or an error chunk.

**Agent captions:**

1. The first `text_delta` of a segment opens a writer with
   `active.room.local_participant.stream_text(topic=TRANSCRIPTION_TOPIC, attributes=..., sender_identity=active.identity)`.
   The attributes are:
   - `ATTR_TRANSCRIBED_TRACK` = the speaking participant's track sid;
   - `ATTR_SEGMENT` = `uuid4().hex`;
   - `ATTR_FINAL` = `"false"`.
2. Every delta in the segment is written to that writer. Deltas arrive paced with the audio (`realtime_pool.py:210`),
   so the caption keeps up with speech.
3. At the boundary, the writer is closed. One final message is then sent with
   `send_text(full_text, topic=TRANSCRIPTION_TOPIC, attributes={same track, same segment, ATTR_FINAL: "true"})`. For
   an interrupted segment, the final text is what was delivered.

**Caller captions:** one single-message text stream, `stream_text(...)`, opened on the listening participant,
`_participants[0]`, written once and closed, with these values:
- `sender_identity=self._caller_identity`;
- `ATTR_TRANSCRIBED_TRACK` = the caller's track sid;
- a new `ATTR_SEGMENT`;
- `ATTR_FINAL="true"`.

`send_text` is not used here because it takes no `sender_identity` (`livekit` 1.1.20), and the caller's words must show as
the caller's. The agent's final message still uses `send_text`: its sender is the speaking agent's own participant.

**Rules:**

1. **Captions never hold up delivery.** `deliver_chunk` runs on the Response Handler's thread, which delivers audio for
   every room in the process, and a caption write is a LiveKit call that waits for the server. So there is one ordered
   caption queue per gateway, drained by one task (`_caption_task`) on the gateway's own loop, started in `start()`:
   - `deliver_chunk` and the caption helpers only **enqueue** an operation (open and write a delta, close a segment, a
     caller caption) with `loop.call_soon_threadsafe(queue.put_nowait, operation)`. They never await caption I/O.
   - The task performs the `stream_text` / `write` / `aclose` / `send_text` calls in order.
   - A segment whose stream failed to open or write is marked failed: its later writes are skipped, with **one**
     WARNING per segment, never one per delta.
   - `_release()` lets the queue drain for at most `CAPTION_DRAIN_SECONDS` (1.0), then cancels the task.
   Audio and chat delivery do not depend on captions.
2. The turn-end `lk-chat` message (`_publish_text`, `:580`) is unchanged.
3. A gateway whose agent participant has no track yet (the first second of a call) skips that segment's caption. The
   line (2.2) is still produced.

#### 2.4 Opening prompt (C5)

```python
def opening_prompt(self, participant_identity: str) -> Optional[str]:
    """What the conversation is asked to say when a caller's microphone appears; None sends nothing.

    Called on every caller track subscription, a rejoin after a page reload included.
    """
    return f"A user named {participant_identity} just connected their microphone. Say a very short hello to them and confirm you are connected!"
```

- `_greet` (`:255`) stages `AgentRequestText(prompt=...)` only when `opening_prompt` returns a non-empty string.
- The default text is the current text at `:258`, word for word.

### 3. Start and stop a gateway at runtime (C3)

#### 3.1 `StatefulEdgeAdapter` readiness (`integration/adapter/base.py`)

```python
def _mark_ready(self) -> None:
    """Called by the edge once its platform connection is up; wakes a waiting background start."""

def wait_ready(self, timeout: float) -> bool:
    """True once the edge called _mark_ready, False on timeout."""
```

- These are backed by a `threading.Event`, created in `__init__`.
- `LiveKitEdgeGateway.start()` calls `_mark_ready()` straight after `self._connected = True` (`livekit/adapter.py:193`).
- An edge that never calls `_mark_ready()` still works under boot-time hosting (`IOHandler.run(gateways=...)`). It
  cannot use the background start (3.2), whose wait would time out.

#### 3.2 `GatewayRunner` (`integration/adapter/gateway.py`)

```python
class GatewayRunner:
    READY_TIMEOUT_SECONDS: float = 30.0

    def start(self) -> None: ...                       # unchanged contract: blocking, used by IOHandler
    def start_background(self, ready_timeout: float | None = None) -> None:
        """Run the gateway on a thread of its own and return once its edge is ready.

        :raises RuntimeError: If already started.
        :raises Exception: Whatever the edge's start() raised, re-raised here.
        :raises TimeoutError: If the edge is not ready in time; the gateway is stopped first.
        """
    def stop(self, timeout: float | None = None) -> None:
        """Stop a background gateway and wait for its thread; safe to call twice, and before a start."""

    @property
    def running(self) -> bool: ...
```

- `_run_until_shutdown` (`gateway.py:56`) loops while
  `not ThreadRunner.shutdown_event.is_set() and not self._stop_requested.is_set()`. Either signal leads to the same
  existing stop path: `adapter.stop()`, then the bounded wait, then cancel.
- `start_background()`:
  1. Creates a daemon `threading.Thread(name=f"gateway-{adapter.name}-{adapter.session_id}")` that runs `start()`,
     storing any exception.
  2. Waits until the edge is ready, the thread has ended (the stored exception is re-raised), or the timeout passes
     (`stop()` is called, then `TimeoutError` is raised).
- `stop()` sets `_stop_requested`, then joins the thread for up to `timeout or GRACEFUL_STOP_TIMEOUT_SECONDS + 1`.

**Rules:**

1. **A background gateway never ends the process.** A boot-time gateway runs as a
   `ThreadRunner.Task(stop_all_on_failure=True)` (`pipeline/io_handler.py:169`), so its failure brings the process
   down. A background one reports its failure to the caller instead. One meeting failing must not end the others.
2. Process shutdown still stops background gateways, because the loop also watches `ThreadRunner.shutdown_event`.
3. `start()` keeps registering, then unregistering, in its `finally` (`gateway.py:48-54`), so a stopped background
   gateway leaves the registry.

#### 3.3 `StatefulEdgeRegistry` (`integration/adapter/registry.py`)

- `unregister(session_id, adapter=None)`: when `adapter` is given, the entry is removed only if it is that adapter.
  `GatewayRunner.start()` passes its own adapter, so a stopped gateway cannot remove a newer one registered under the
  same id.
- `unregister` records `session_id` as **recently ended**, with a time, in a class-level dict under the existing lock.
- `recently_ended(session_id) -> bool` is true for `ENDED_TTL_SECONDS = 60.0` after an unregister. Expired entries are
  pruned on each `unregister` and `recently_ended` call.
- `register` clears any recently-ended mark for its session id.
- `reset()` also clears the marks.

### 4. End a realtime session at once (C4)

#### 4.1 The control message

- `pipeline/envelope.py` gets `ATTR_REALTIME_END = "realtime_end"`. Its presence on an **input** message means *the
  edge for this session has ended*.
- `IntegrationProducer.enqueue(adapter_name, request, attributes: Optional[Dict[str, str]] = None)`
  (`integration/adapter/producer.py:61`) merges `attributes` after the integration and reply attributes. A key that
  collides with one of those raises `ValueError`.
- The body is an ordinary `BaseRunRequest` with the session id, the agent and `requests=[]`
  (`core/model.py:470` allows an empty list). The group id is the session id, so on every transport the control
  arrives after that session's earlier input.

#### 4.2 Sending it (`integration/livekit/adapter.py`)

`_release()` (`:229`) starts with `await self._send_session_end()`. That method runs once per gateway:

1. Set `_ending = True`. From now on, `_stage_request` drops new frames.
2. Wait, for up to `SESSION_END_TIMEOUT_SECONDS = 2.0`, for `_pending` to drain. `_drain_requests` now calls
   `self._pending.task_done()` after each send, so `_pending.join()` can be awaited.
3. Send the control with
   `await asyncio.to_thread(self._producer.enqueue, self.name, self._enqueue_end(), {ATTR_REALTIME_END: "true"})`.
4. A failure here is logged at WARNING. The connection then ends by idle eviction, as it does today.

The rest of `_release` is unchanged.

`_enqueue_end()` is a new `StatefulEdgeAdapter` helper, the twin of `_enqueue` (`base.py:300`), with `requests=[]`.
Any edge can use it.

#### 4.3 Receiving it (`pipeline/realtime_pool.py`)

- `dispatch` (`:533`), straight after its shutdown check: if `attributes.get(ATTR_REALTIME_END)` is set, it calls
  `self.end_session(body.session_id)` and returns. It never creates a connection for the control.
- `end_session(session_id)`:
  1. Removes the session's connection from `_connections`.
  2. Records `_ended[session_id] = time.time()`.
  3. Schedules `conn.close()` on the pool loop and waits for it up to `_SEND_TIMEOUT_SECONDS`.
  4. Logs `Realtime session {id} ended by its edge` at INFO.
- In `dispatch` and `get_or_create`, input for a session in `_ended` younger than `_ENDED_SESSION_TTL_SECONDS = 60.0`
  is dropped with a DEBUG log. The idle sweep in `_wait_for_shutdown` (`:389`) prunes expired entries.
- The ECS realtime runner already passes the message's custom attributes to `dispatch`
  (`deployment/aws/containerized/akagentrunner.py:329`), so it needs no change.

#### 4.4 Trailing output (`pipeline/response_handler.py`)

- `_deliver_realtime` (`:172`): when no edge is registered but `StatefulEdgeRegistry.recently_ended(message.group_id)`
  is true, it logs at DEBUG and returns instead of raising. The message is acked, not retried.
- `_deliver_realtime_failure` (`:208`) returns quietly in the same case.

#### 4.5 Back off reconnects (C6)

A native session that fails right after it opens (a bad setting, a quota error) used to be replaced by the next audio
frame, about every 100 ms, and each replacement failed again, sent an error chunk to the room and hit the model provider.
`RealtimeConnectionPool` now backs off per session:

- `_failures: dict[str, tuple[int, float]]` holds the consecutive failures and the time a retry is next allowed, guarded
  by `_conn_lock`.
- **A failure is recorded** when `get_connection` evicts a connection that is `closed` because it failed (a connection
  ended by `end_session`, or evicted as idle, is removed elsewhere and is not a failure), and in `_discard_failed`.
- **The delay** is `min(_RECONNECT_MAX_SECONDS, _RECONNECT_BASE_SECONDS * 2 ** (n - 1))`: 1, 2, 4... s, at most 30 s.
- `dispatch` drops input, with a DEBUG log, while `time.time() < retry_at`. It never opens a connection then.
- **Reset:** `RealtimeConnection.produced_output` is set by its first `audio_delta`, `transcript_delta` or `done`. When a
  connection that produced output later fails, the count restarts at 1; one that never did adds 1.
- `end_session` clears the session's entry, as does a pool reset; the idle sweep prunes entries that expired long ago.

### 5. Consumer changes (AK)

- **`pipeline/realtime_pool.py`:** sections 1.3 and 4.3. The `TextDelta`/`AudioDelta` paths are verified unchanged.
- **`framework/adk/adk.py`, `framework/openai/openai.py`:** only sections 1.4 and 1.5. Speaker, audio and turn mapping
  are unchanged.
- **`integration/livekit/adapter.py`:** sections 2.2, 2.3, 2.4, `_mark_ready` (3.1) and 4.2.
- **`integration/adapter/{base,gateway,registry,producer}.py`:** sections 2.1, 3 and 4.1.
- **`pipeline/response_handler.py`:** section 4.4.
- **`pipeline/agent_runner.py`, ECS `akagentrunner.py`, `pipeline/io_handler.py`:** no change. Verified: both
  realtime runners hand the attributes to `dispatch`, and IOHandler starts `RealtimeAgentRunner` without boot
  gateways in REALTIME mode (`io_handler.py:146`).
- **`integration/agui/mapping.py`:** no change. `to_agui` returns `None` for an event type with no AG-UI equivalent
  (`:69`), so `InputTranscript` is dropped there, as `AgentChanged` already is.

### 6. Config changes

**No `AKConfig` changes.** These are new class constants, each overridable by subclassing:

| Constant | Owner | Value | Why it is not config |
|---|---|---|---|
| `READY_TIMEOUT_SECONDS` | `GatewayRunner` | 30.0 | A hosting detail, like the existing `GRACEFUL_STOP_TIMEOUT_SECONDS` (`gateway.py:21`) |
| `SESSION_END_TIMEOUT_SECONDS` | `LiveKitEdgeGateway` | 2.0 | Sits beside `PLAYOUT_WAIT_SECONDS` (`livekit/adapter.py:49`) |
| `ENDED_TTL_SECONDS` | `StatefulEdgeRegistry` | 60.0 | A safety window, not user behaviour |
| `_ENDED_SESSION_TTL_SECONDS` | `realtime_pool` module | 60.0 | Matches `_IDLE_TIMEOUT_SECONDS` (`realtime_pool.py:33`) |
| `_RECONNECT_BASE_SECONDS`, `_RECONNECT_MAX_SECONDS` | `realtime_pool` module | 1.0, 30.0 | The back-off after a failed native session (4.5); a safety window, not user behaviour |
| `CAPTION_DRAIN_SECONDS` | `LiveKitEdgeGateway` | 1.0 | How long a stopping gateway lets queued captions finish (2.3) |
| `TRANSCRIPTION_TOPIC`, `ATTR_*` | `LiveKitEdgeGateway` | LiveKit's names | Protocol constants |

### 7. Behavioural changes (AK)

1. **ADK realtime sessions now emit `InputTranscript` chunks with no change to app code**, because ADK transcribes the
   caller by default (1.4). That is one more output message per caller utterance. *Intentional: it is the feature.*
2. **OpenAI realtime sessions emit them once the app turns on transcription** (1.5). *Intentional.*
3. **A bring-your-own edge receives a new event type in `deliver_chunk`.** `StatefulEdgeAdapter.deliver_chunk` is
   abstract (`base.py:323`), so every edge implements it. An edge that handles only the types it knows (as LiveKit
   does, `livekit/adapter.py:360`) ignores it with no change. One that rejects unknown types has to ignore it.
   *Intentional, and documented as a contract change for BYO edges.*
4. **The LiveKit gateway publishes `lk.transcription` text streams** for every agent segment and caller line. That is
   new room traffic, and standard LiveKit components show it. *Intentional.*
5. **A LiveKit gateway that stops or loses its room sends an end-of-session control.** The pool closes the native
   session at once, instead of after up to 300 s, and drops that session's input for 60 s. *Intentional: it frees model
   sessions.*
6. **The Response Handler drops, instead of retrying, realtime chunks for an edge unregistered in the last 60 s.**
   *Intentional: they belonged to a call that is over.*
7. **`StatefulEdgeRegistry.unregister` only removes its own adapter** when given one. *Intentional: it prevents a stale
   stop from removing a newer edge.*
8. **A session whose native connection failed is not reopened by the next frame.** Input is dropped for 1, 2, 4... s (at
   most 30 s) after each consecutive failure (4.5). *Intentional: it stops a loop of failing sessions that each sent an
   error to the room and hit the model provider.*
9. **Captions are written by one task per gateway**, off the delivery thread (2.3). *Intentional: a slow caption write
   can no longer delay audio.* A caption can therefore reach the room a moment after the audio it belongs to.

**Non-changes:**
- The `RealtimeRunner` abstract methods.
- The `StreamChunk` fields.
- The `AgentChanged` shape.
- The `lk-chat` publishing.
- The default opening prompt text.
- Boot-time gateway hosting, including its process-ending failure.
- `AKConfig` and its YAML / `AK_*` variables.
- Data written before the change. AK persists nothing new.

