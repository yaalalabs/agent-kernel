# #810: Native realtime agents and handoffs — Implementation Spec

This specifies how to build the [design](design.md). OpenAI Agents SDK and Google ADK own live model sessions, agent turns, handoffs, and tool execution. Agent Kernel (AK) owns the queue and LiveKit edge. For example, a billing agent can hand a call back to a coordinator using its SDK's handoff feature; AK only changes which LiveKit participant speaks.

## Design

### Boundary and existing architecture

1. Keep the existing `Agent.realtime_runner_cls` selection point (`core/base.py::Agent.realtime_runner_cls`) and `RealtimeRunner` ABC (`core/realtime/runner.py`). This is already the pluggable class seam for built-in and bring-your-own runners. Do not add a second provider factory or import either SDK from `core/`.
2. Keep `RealtimeConnection` and `RealtimeConnectionPool` (`pipeline/realtime_pool.py`): one connection per AK session ID, one pool event loop, queue transport, 24 kHz edge PCM, input conversion, ordered output, pacing, barge-in, idle eviction, and shutdown. Framework SDKs have no responsibility for this AK/LiveKit boundary.
3. Keep the `StreamChunk` and `AgentChanged` queue shape and LiveKit participant selection (`integration/livekit/adapter.py`). Never send agent participant audio or chat back to a model as caller input (`_own_identities`). One native framework conversation serves the room; only its active speaker is unmuted. Handoff A → B → A stays inside that conversation, with no audio loop between agents.
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

- Delete `execute_tool()` and `send_tool_result()` from the ABC. Delete `tool_call` from its callback contract. The only callback event names are `audio_delta`, `transcript_delta`, `input_transcript`, `agent_changed`, `interrupt`, `speech_started`, `done`, and `error`. An event has the current dictionary payload shape documented by the ABC; audio is base64 PCM16 at `output_sample_rate` with `message_id`.
- Do not add a queue-delivery callback to the ABC for playback tracking. A queue send is earlier than actual LiveKit playout, so it must not advance the SDK tracker. Use the SDK's default playback estimate until a reliable edge playout signal is available; document that estimate and test interruptions.
- `team()` returns a stable list of known speaking-agent names, without constructing a new graph. A default `initial_speaker(agent)` returns `agent.name`; an adapter with a non-speaking root returns `None` (the ADK adapter does for a `Workflow`). The pool enqueues the initial `AgentChanged` only when there is an initial speaker. Subsequent adapter `agent_changed` events use the same FIFO pacing queue. The adapter must emit a change before the new speaker's audio or transcript. A name discovered after connection may extend the roster in that change event.
- A realtime session neither injects nor stores the session's `framework_context`; an adapter leaves the key alone (stated in the `RealtimeRunner` docstring).
- All adapter state belongs to the runner instance created for one connection. The callback is awaited in native event order. `disconnect()` is idempotent. Startup that fails after opening SDK resources closes them before raising. Background listeners report unexpected failure through `error` and never report normal `disconnect()` as an error.

### Realtime pool

In `ak-py/src/agentkernel/pipeline/realtime_pool.py`:

- Remove `_execute_tool_and_reply()` and all imports used only by that path. `handle_framework_event("tool_call", ...)` must call `_fail()` with a message naming the removed contract, close/evict the connection, and never execute the tool. Unknown event names must likewise fail with the event name instead of being ignored. These failures become terminal error chunks through the existing queue path.
- Set the tool context for the call, once, in `RealtimeConnection.connect()`: `ToolContext(runtime, agent, session, [])` and `Session.current_session` and `Agent._activate()`, around `adapter.connect()`, and reset them after. The native session's tasks are created inside that call and inherit the context (OpenAI's websocket listener task and ADK's listener task), so a tool run by the SDK sees `ToolContext.get()`, `Session.current()` and `Agent.current()` as it does on the unary path. The session lock is **not** taken: a call is one long-lived session, and holding the lock for it would block every other run of that session (the base pool took it per tool call). The context is set once per connection, so it does not follow a tool that an SDK runs on a task created outside the connect call; the OpenAI test drives the real SDK session to show the inheritance.
- Preserve `_interrupt()` semantics: discard audio and transcript still in the pacing queue, keep queued control events, and send `Interrupt`. Do not decide an SDK handoff or call a tool here.
- On failed `connect()` or its 15-second `get_or_create()` wait, remove only that connection's registry entry, cancel its pending connect future if needed, and await/arrange `conn.close()` on the pool loop. Do not remove a replacement connection inserted concurrently. Preserve the 10-second send bound, 5-minute idle eviction, and 2-second shutdown grace unless a focused test proves a change necessary.
- The registry lock protects connection creation and eviction, not SDK calls. Input from consumer threads reaches the single pool loop through `run_coroutine_threadsafe`. A second AK session has a separate runner, SDK session, and ADK queue.

### OpenAI adapter

Replace `OpenAIRealtimeRunner` in `ak-py/src/agentkernel/framework/openai/openai.py` with a thin owner of one native `agents.realtime.RealtimeRunner` and `RealtimeSession`. Remove raw `AsyncOpenAI` socket handling, `_activate`, `_offered_tools`, `_offered_handoffs`, `_switch_to`, manual JSON tool replies, custom transcript replay, and manual reconnection. Do not copy or mutate the native agent graph to wrap tools.

1. Require the wrapped native root to be `RealtimeAgent`. `OpenAIModule` may still load ordinary `agents.Agent` for unary use; selecting it for realtime raises `TypeError` before opening a socket. The native realtime graph uses `RealtimeAgent.handoffs`, including SDK `realtime_handoff(...)` objects. Walk only public graph fields for the optional roster; if a dynamic handoff cannot be listed early, announce it when its SDK event arrives. Do not substitute regular `agents.handoff` or an AK routing tool.
2. Resolve `Module.run_options` once at connection start with `agent.resolve_run_options(session, [])`. Accept only `model` and `config` (for `RealtimeRunner(...)`) and `model_config` (for `RealtimeRunner.run(...)`); reject unknown or reserved keys (`starting_agent`, and `context`, since a realtime session does not carry `framework_context`) with agent name and key. The SDK's model and audio settings remain native objects/dicts. The example must show where the OpenAI model and one session voice are set; `RealtimeAgent` itself has no per-agent model or voice.
3. Enter the native session and consume its async event stream in one listener task. `append_audio()` base64-decodes to bytes and calls `session.send_audio()`. `send_text()` calls `session.send_message()`. The SDK owns tool execution, handoffs, approval state, history, guardrails, and model transport. The adapter never handles a raw tool call.
4. Map high-level `audio` to `audio_delta` using `event.audio.data`. Map the public `raw_model_event` payload types `RealtimeModelTranscriptDeltaEvent` and `RealtimeModelOutputTextDeltaEvent` to `transcript_delta`, and `RealtimeModelTurnEndedEvent` to `done`. Map high-level `audio_interrupted` to `interrupt`, `handoff`/a changed `agent_start` to `agent_changed`, and native failure to `error`. Do not map `agent_end` alone to a speaker change. Deduplicate `handoff` and following `agent_start` for the same speaker. Preserve ordering before that speaker's first content. Treat clean end of native iteration as connection closure; it is not a fresh turn.
5. Keep the SDK's default interruption/playback estimate. `RealtimePlaybackTracker.on_play_bytes()` means bytes actually played to the listener, so do not call it from the AK output queue. If the LiveKit edge later exposes reliable playout progress, pass that signal to the SDK tracker as a separate change. Record the current estimate's effect during barge-in tests.
6. An OpenAI `tool_approval_required` event needs a human decision. LiveKit has no approval response route in this design, so do not auto-approve. Reject statically declared approval tools at connect when the public tool definition exposes `needs_approval`; if a dynamic approval event still occurs, call the SDK's `reject_tool_call(call_id)` and fail the AK connection with a clear unsupported-approval error. Keep supported SDK output and tool input guardrails in native execution; `guardrail_tripped` must clear buffered output through the SDK interruption event or an immediate AK `interrupt`, then allow the SDK's own recovery response to continue. Do not silently drop a guardrail or approval tool.
7. Native MCP servers/tools on `RealtimeAgent` stay attached to the native agent. Their actual use must be verified in the installed SDK; if the chosen SDK/model rejects one, surface that native error. AK does not implement an MCP executor. Native resumption or reconnect settings, if the SDK exposes them, are passed through; AK never promises restoration of the LiveKit call after process restart.

The exact event attributes must be confirmed against the pinned `openai-agents` version while implementing; use the SDK's public event types, not raw provider JSON. Current optional extra is `openai-agents>=0.20.0,<0.21` (`ak-py/pyproject.toml`). If a required public event is absent at that floor, raise the floor to the first verified version and update example lockfiles in the same iteration. Do not write a private-SDK workaround.

### ADK adapter

Replace `GoogleADKRealtimeRunner` in `ak-py/src/agentkernel/framework/adk/adk.py` with one native `google.adk.runners.Runner.run_live()` async generator and one `LiveRequestQueue` per AK connection. Remove `BidiGenerateContent` socket creation, copied transfer instructions, tool declarations/results, `_batches`, `_transfers`, `_history`, replay, manual connection switching, and custom SDK retry logic. Preserve the native `BaseAgent` tree or `Workflow` relationships; do not clone the graph.

1. Reuse `GoogleADKSession`'s session service and AK session ID from the unary adapter (`GoogleADKRunner._session`) rather than creating an unrelated store. Create the ADK session before `run_live()`. Build the `App(root_agent=agent.agent, ...)` and ADK `Runner` with `GoogleADKRunner._native_runner`, the helper the unary path also uses (it moves `plugins` from the run options onto the `App`, since ADK refuses them on both). Start consuming `run_live(user_id=..., session_id=..., live_request_queue=..., run_config=...)` before accepting input. The listener owns the generator's lifetime; close queue, generator, and runner resources on stop or startup failure. ADK's graph `Workflow` root is a `BaseNode`, not a `BaseAgent`; widen only the AK wrapper's live root acceptance needed for this native type.
2. `append_audio()` decodes the pool's 16 kHz PCM16 and sends an ADK `types.Blob` through `LiveRequestQueue.send_realtime()`. `send_text()` sends a user `types.Content` through `send_content()`. Do not call Gemini Live directly. Set `input_sample_rate=16000`; output PCM rate comes from ADK's actual live output format and is declared on the adapter for pool resampling.
3. Use each ADK `Event.author` when the event represents a speaking agent. Emit `agent_changed` before the first audio/text of a newly active author. Ignore tool authors and framework/control events for speaker selection. Map output audio, output transcription/text, interruption, completion, and failure into the ABC callback events. One `LiveRequestQueue` continues across native transfers, including A → B → A; ADK, not AK, opens any next Gemini session.
4. Do not validate the graph before starting. A speaking `Workflow` node left without `mode='chat'` or `mode='task'` runs outside the live connection and ADK raises nothing for it, so the examples and docs say to set it. `ParallelAgent` and `LoopAgent` are not checked: they are deprecated and ADK raises `NotImplementedError` for them itself. A `Workflow` root is a container that does not speak: `GoogleADKRealtimeRunner.initial_speaker` returns `None`, so the pool announces no first speaker, and the first speaking node is reported by `_speaker_changed` from ADK's first event, with the roster (`team()` lists the speaking nodes of the workflow graph and every `sub_agents` tree).
5. `Module.run_options` accepts native ADK `Runner` constructor options already split by `GoogleADKRunner._split_run_options()` (`GoogleADKRunner.RUNNER_CONSTRUCTOR_OPTIONS`, `plugins` among them) and a native `run_config` for `run_live()` (`GoogleADKRealtimeRunner.LIVE_OPTIONS`). Reject keys used internally (`session`, `session_id`, `user_id`, `live_request_queue`, root `agent`/`app`, and session service) instead of allowing a duplicate argument. Do not synthesize a `RunConfig` for each native setting AK does not own. Use `Gemini(speech_config=...)` for per-agent voice or `RunConfig.speech_config` for a shared voice; the old `generate_content_config.speech_config` path is not read by `run_live()`.
6. Keep native ADK tools and toolsets attached. ADK executes them and emits their results. A tool requiring confirmation cannot receive a LiveKit decision here, and AK does not check the declaration before opening: ADK has no public static accessor for it, and reading the private `FunctionTool._require_confirmation` would depend on ADK internals. At runtime, detect a confirmation request in the public `Event.actions.requested_tool_confirmations` field, fail the AK connection, and close the live run. ADK's live tool flow refuses such a call itself; AK must not try to resume or approve it. Never answer yes automatically or leave a pending confirmation hidden. Confirm the event path against ADK 2.7.0 before shipping. The runtime event is the only handling. Native plugins/guardrails are passed to ADK when supported by `run_live`; any option that is neither a `Runner` constructor option nor `run_config` (`context_cache_config` included) is rejected by name at connect. Native session resumption is optional and covers ADK ↔ Gemini only.

Raise the optional `google-adk` floor from `>=1.24.0` to `>=2.7.0` in `ak-py/pyproject.toml`, which includes the live transfer ordering fix. `adk.py` imports `google.adk.workflow.Workflow` at module level, which ADK 1.x lacks, so the floor is a breaking change for every ADK user and goes in the release notes. In a minimum-version test environment, measure what happens when `transfer_to_agent` is refused or invalid; do not assume the call remains usable. Update lockfiles of edited ADK examples. The [ADK live workflow guide](https://adk.dev/live/workflows/) documents one queue, per-author output, and the unsupported legacy loop/parallel agents; [live configuration](https://adk.dev/live/configuration/) documents voice placement.

### Scope: native features only

Realtime runs native agent features. AK hooks and AK guardrails are not part of the native live path (the base path did not run them either). The OpenAI and ADK agent wrappers attach AK system tools (multimodal, sandbox, schedule, knowledge base) and their guidance as in every other mode, because the tool context they need is set by the pool (above). An ADK `Workflow` root holds no tools or instructions, so they are attached to the speaking nodes inside it (`GoogleADKAgent._attach_workflow_system_tools`), each looked up by its own name for the `agents` allow-lists; ADK keeps its own copy of each node in the graph, so they go on the graph's copy, and an inner agent the application also registers with the module gets them twice. A realtime session neither injects nor stores `framework_context`. Native tools declared on the SDK agents run through the SDK.

### First-release support list

| Capability | OpenAI live adapter | ADK live adapter |
| --- | --- | --- |
| Agent handoffs and agent-specific native tools | Native `RealtimeAgent` session | Native `run_live()` / `LiveRequestQueue` |
| Native MCP tools or toolsets | Pass `RealtimeAgent.mcp_servers` through; test SDK/model acceptance | Pass native ADK toolsets through; test SDK/model acceptance |
| Approval or confirmation | Reject: LiveKit has no decision route | Reject: LiveKit has no decision route |
| Guardrails | Native realtime output/tool-input guardrails; map interruption | Native live plugins/callbacks where ADK runs them; reject unsupported declarations |
| AK hooks and AK guardrails | Not automatically invoked by the native live runner | Not automatically invoked by the native live runner |
| AK system tools and tool context | Attached; `ToolContext`, `Session.current()`, `Agent.current()` set by the pool | Attached (on a `Workflow`, to its speaking nodes); same, plus ADK's own `ToolContext` by id |
| Native connection recovery | Follow SDK behavior; no AK replay | ADK session resumption if configured; no AK replay |
| LiveKit call after process restart | Unsupported | Unsupported |

The implementation tests each “pass through” case. If a native SDK rejects it, expose that error and document the tested limit; do not add an AK substitute.

### Consumer changes

- `OpenAIModule`/`OpenAIAgent` keep unary `Agent` support. The realtime path accepts `RealtimeAgent`; its wrapper must avoid assumptions specific to ordinary `Agent` when reading instructions. `OpenAIToolBuilder.bind()` remains a native `function_tool` binder for callers that choose it; the realtime runner no longer rebinds its output.
- `GoogleADKModule`/`GoogleADKAgent` keep native agent wrapping and unary behavior. The live path also accepts ADK's graph `Workflow` root. The realtime runner does not call `GoogleADKToolBuilder._wrap()` itself or replace ADK toolsets with function declarations.
- `RealtimeConnectionPool` and the queue consumer keep their existing transport and AK session IDs. LiveKit keeps room participants, muting, and input filtering; only speaker events from native SDKs change the selected participant.
- Migrate `examples/api/livekit-voice/openai/{in_memory,handoffs}` and any other OpenAI realtime sample that builds ordinary `Agent` to `RealtimeAgent`. Migrate ADK samples' per-agent voice to native `Gemini(speech_config=...)`; remove documentation of manual transfer/tool limits that no longer apply. Update `docs/docs/architecture/realtime-internals.md`, `docs/docs/integrations/livekit.md`, and relevant example READMEs with a per-SDK capability table.

### Config changes

- No new `AKConfig` field. `execution.realtime.playback_lead_ms` (default 50) and `input_batch_ms` (default 100) remain the edge controls (`core/config.py::_RealtimeConfig`). Queue and LiveKit settings stay as they are. Existing YAML and `AK_*` variables keep parsing the same way. Existing data in AK session stores and output queues keeps its layout.
- `Module.run_options` remains the per-agent native option seam (`core/module.py::Module.run_options`). The realtime runner resolves it once per connection, not once per audio frame. A chosen SDK option must have a named destination as described above; bad options fail before any native call. No new `enabled`, tool, handoff, or reconnect flag is introduced.
- Native SDK settings may require **application code migration**: OpenAI model/voice move from ordinary `Agent` fields into realtime runner/session configuration; ADK per-agent voice moves from `generate_content_config.speech_config` into `Gemini(speech_config=...)`. Document exact before/after examples. OpenAI's one-session voice cannot switch after speech begins.

### Behavioural changes

1. **Intentional:** OpenAI realtime requires `RealtimeAgent`; ordinary OpenAI `Agent` now fails at live connect. Unary OpenAI runs remain valid.
2. **Intentional:** OpenAI and ADK native SDKs execute their own tools and handoffs. The pool no longer handles a `tool_call`; BYO runners emitting it fail loudly.
3. **Not a change from base:** AK system tools and their guidance stay attached in realtime mode (on an ADK `Workflow`, to its speaking nodes), and a tool sees `ToolContext`, `Session.current()` and `Agent.current()` (set by the pool once per call; the session lock is not held while a tool runs). Realtime does not use `framework_context`, as before.
4. **Intentional:** Approval-requiring tools cannot proceed through LiveKit without a decision route. A runtime request from an OpenAI tool with `needs_approval` or an ADK `FunctionTool` with `require_confirmation` is rejected and surfaced as a connection error. No implicit approval. (Base left an OpenAI tool needing approval out of the offered tools with a warning.)
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
| `ak-py/tests/test_adk_runner.py` or a focused `test_adk_realtime.py` | Patch native `Runner.run_live` and `LiveRequestQueue` at `agentkernel.framework.adk.adk`. Test one queue for A → B → A, native tool events without pool execution, author-to-speaker mapping, audio/text input, `RunConfig` and voice, a workflow node left in `single_turn`, confirmation failure, failed startup cleanup, and per-session separation. Run refused transfer against `google-adk==2.7.0` in an optional SDK integration test. |
| `ak-py/tests/test_livekit_edge_adapter.py` | Verify starting roster, native speaker changes, mute order and edge audio/text attribution; own agent participant audio/chat stay excluded. Cover an ADK workflow root with no initial speaker, whose first speaking author is announced with the roster. |
| `ak-py/tests/test_ecs_akagentrunner_realtime.py` | Keep queue consumer routing tests; verify the pool still creates one connection per session and reports a native startup failure without acking it as success. |
| Tool context | `test_realtime_pool.py`: a task the adapter starts while connecting sees the tool context, session and agent, and none is left set after `connect()`, failed or not. `test_openai_realtime.py`: a tool run by the real SDK session sees them (its `ScriptedModel` emits events from a listener task created while connecting, as the real transport does). `test_adk_realtime.py`: a tool run inside `run_live()` sees them; AK system tools are attached to a realtime agent, and to the speaking nodes of a `Workflow` rather than its root. |

Run focused tests from `ak-py/` with `uv run pytest tests/test_realtime_pool.py tests/test_openai_runner.py tests/test_adk_runner.py tests/test_livekit_edge_adapter.py tests/test_ecs_akagentrunner_realtime.py`; run `make lint-check-all` from the repo root before implementation is considered complete. Credentialed live-call tests require API keys and are a separate verification gate, not a reason to skip the deterministic tests. Record the installed SDK versions used for the SDK integration checks.


## Edge additions for realtime calls (C1, C4 to C7)

The full detail of the additions (the caller's words as an event, ending a session at once, the opening prompt, reconnect back-off). Live captions (C2) are not part of Agent Kernel: captions are the application's. C3 (an API for application code to start a gateway in the background and wait until it is ready) is not part of Agent Kernel. C7 is a different thing: gateways started and ended by the platform's own signed lifecycle webhooks, hosted by AK the way it hosts a messaging webhook. The application still decides which rooms get one (`should_start`). The C numbers are kept so they match the code and the architecture skill. Observing a call from server code and sending text into it are not part of this change (see design.md, Non-goals).

### 1. The caller's words as an event (C1)

#### 1.1 `InputTranscript` (`ak-py/src/agentkernel/core/event.py`)

```python
class InputTranscript(StreamEventBase):
    """One finished utterance of the caller in a realtime conversation, as text.

    Reported when the framework finishes transcribing it, which may be after the response that follows
    the utterance; a transcript built from the stream follows the framework's report order.
    Reported only when the framework's own input transcription is on; an edge that does not show a
    transcript ignores it.
    """

    type: Literal["input_transcript"] = "input_transcript"
    message_id: str   # the framework's item/event id, or uuid4().hex when it has none
    content: str      # the finished text; never empty
```

- Added to the `StreamEvent` union, right after `AgentChanged` (`core/event.py`).
- It is not projected into `StreamChunk.delta`. `delta` stays assistant prose only (`core/model.py::StreamChunk`).

#### 1.2 The `RealtimeRunner` contract (`ak-py/src/agentkernel/core/realtime/runner.py`)

- The `connect()` docstring's event list (`runner.py`) gains one entry:
  - `input_transcript`: `{"text": str, "message_id": str}`. One finished caller utterance; report it only when the
    text is not empty, and never report partial text.
- The abstract methods do not change. A bring-your-own runner that never reports the event keeps working.

#### 1.3 The realtime pool (`ak-py/src/agentkernel/pipeline/realtime_pool.py`)

- **`handle_framework_event`** puts `input_transcript` on `_audio_queue`, as it does `done` and
  `agent_changed`. An unknown event still fails the connection.
- **`_interrupt`** keeps a queued `input_transcript` with the control events. It is the caller's words, not
  agent output the caller will no longer hear.
- **`_pacing_loop`** emits `StreamChunk(event=InputTranscript(message_id=..., content=data["text"]))`. Like a
  `transcript_delta`, it does not reset the pacing window.

**Rules:**

1. **The order is "behind queued output", which settles the design's open question.** The caller's line rides
   `_audio_queue`, so it reaches the edge after any agent output the caller has already heard.
   - In practice the queue is empty by then. A barge-in clears it (`_interrupt`). Transcription finishes only after
     the caller stops speaking, and a `speech_started` with audio still queued is itself a barge-in.
   - So the delay is at most the playback lead (`execution.realtime.playback_lead_ms`).
2. `_queued_audio` counts audio only. It is unchanged by this event.

#### 1.4 ADK adapter (`ak-py/src/agentkernel/framework/adk/adk.py`)

In `GoogleADKRealtimeRunner._handle_event`, the early return for `event.author == "user"` becomes:

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

In `OpenAIRealtimeRunner._handle_model_event`, add one branch:

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

### 2. Opening prompt and join (C5)

```python
def opening_prompt(self, participant_identity: str) -> Optional[str]:
    """What the conversation is asked to say when a participant joins the room; None sends nothing.

    Called once for every caller that joins, a rejoin after a page reload included, whether or not
    their microphone is published yet.
    """
    return f"A user named {participant_identity} just connected. Say a very short hello to them and confirm you are connected!"
```

- `_greet` stages `AgentRequestText(prompt=...)` only when `opening_prompt` returns a non-empty string.
- A caller already in the room when the gateway joins is greeted from `start()`: LiveKit raises `participant_connected`
  only for later joins. The listener room's `remote_participants` are read straight after its join returns, with no
  await between, so a participant who joins from then on is greeted by the event alone, never twice.
- The conversation opens from `_on_participant_connected`, on the room's `participant_connected` event, not from a track subscription: a caller who joins muted (and may stay muted for the whole call) must still start the conversation, which waiting for a microphone prevented. An agent participant of the gateway's own team is skipped.
- The default text is the base text without the words "their microphone". The gateway also holds a team announcement that arrives before the first participant has joined (`_pending_team`, under a lock) until it is in the room, and a handoff to an agent the roster lacked joins as a participant of its own rather than binding to the first one.

### 3. End a realtime session at once (C4)

#### 3.1 The control message

- `pipeline/envelope.py` gets `ATTR_REALTIME_END = "realtime_end"`. Its presence on an **input** message means *the
  edge for this session has ended*.
- `InboundRequest.end_session: bool = False` (`integration/adapter/base.py`): the end-of-session control. `IntegrationProducer.enqueue`
  (`integration/adapter/producer.py`) stamps `ATTR_REALTIME_END: "true"` when it is set, beside the integration and reply
  attributes; its signature is unchanged and no edge imports `pipeline.envelope`.
- The body is an ordinary `BaseRunRequest` with the session id, the agent and `requests=[]`
  (`core/model.py::BaseRunRequest` allows an empty list). The group id is the session id, so on every transport the control
  arrives after that session's earlier input.

#### 3.2 Sending it (`integration/livekit/adapter.py`)

`_release()` starts with `await self._send_session_end()`. That method runs once per gateway:

1. Set `_ending = True`. From now on, `_stage_request` drops new frames.
2. Wait, for up to `SESSION_END_TIMEOUT_SECONDS = 2.0`, for `_pending` to drain. `_drain_requests` now calls
   `self._pending.task_done()` after each send, so `_pending.join()` can be awaited. If staged input is still unsent after
   that, **do not send the control**: it would pass that input, and the pool would end the session and drop the input as
   late. Log a WARNING; the connection then ends by idle eviction, as it does today.
3. Send the control with
   `await asyncio.wait_for(asyncio.to_thread(self._producer.enqueue, self.name, self._enqueue()), timeout=SESSION_END_TIMEOUT_SECONDS)`.
   The same bound applies, so a broker that does not answer cannot hold up a stopping gateway (the thread finishes on its own).
4. A failure or timeout here is logged at WARNING. The connection then ends by idle eviction, as it does today.

The rest of `_release` is unchanged.

`StatefulEdgeAdapter._enqueue(request=None)` builds it: with no message the request carries `requests=[]`.
Any edge can use it.

#### 3.3 Receiving it (`pipeline/realtime_pool.py`)

- `dispatch`, straight after its shutdown check: if `attributes.get(ATTR_REALTIME_END)` is set, it calls
  `self.end_session(body.session_id)` and returns. It never creates a connection for the control.
- `end_session(session_id)`:
  1. Removes the session's connection from `_connections` and clears its back-off entry from `_failures`.
  2. Schedules `conn.close()` on the pool loop and waits for it up to `_SEND_TIMEOUT_SECONDS`.
  3. Logs `Realtime session {id} ended by its edge` at INFO.
- The session id is not blocked afterwards: later input for it opens a new connection.
- `StatefulEdgeRegistry.unregister(session_id, adapter=None)` removes the entry only when it is `adapter`, if one is given. `_EdgeRunner.start()` passes its own adapter in its `finally`, so a stopped gateway cannot remove a newer one registered under the same id; an app that hosts rooms at runtime can call `start()` on a thread of its own.
- The ECS realtime runner already passes the message's custom attributes to `dispatch`
  (`deployment/aws/containerized/akagentrunner.py`), so it needs no change.

#### 3.4 Back off reconnects (C6)

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
- `end_session` clears the session's entry, as does pool shutdown; the idle sweep prunes entries whose retry time passed more than the idle timeout ago.
- **A failed connect is reported.** `_discard_failed` schedules `RealtimeConnection.fail_to_connect(error)`, which
  emits one terminal `StreamChunk(error="Realtime session could not start: ...", done=True)` with the connection's
  delivery context and then closes what the connect opened. Without it the room would hear nothing: the consumer nacks
  the input, the redelivery falls in the back-off and is acked and dropped, so the input never reaches
  `on_permanent_failure`. One chunk per failed connect is at most one per back-off window.
- **Idle eviction is not a failure.** The idle sweep marks a connection closed and removes it in one critical section,
  so `get_connection` never sees an idle connection still registered and closed.

### 4. One room per call (C7)

#### 4.1 `_EdgeRunner.stop()` (`integration/adapter/lifecycle.py`)

- `GatewayRunner` becomes `_EdgeRunner`, private, moved from `gateway.py` (deleted) into `lifecycle.py` beside its one caller; removed from
  `integration/adapter/__init__.py`'s exports, and `IOHandler.run` loses its `gateways=` parameter and thread loop. `EdgeLifecycleRESTRequestHandler` is the only host; every example mounts it.
- A per-instance `threading.Event`, set by `stop()`; `_run_until_shutdown` loops while neither it nor
  `ThreadRunner.shutdown_event` is set, then runs the same graceful stop (adapter `stop()`, bounded by
  `GRACEFUL_STOP_TIMEOUT_SECONDS`). `start()` then unregisters the adapter as before.
- A stop requested before the loop begins (or a shutdown already under way) returns at once, without calling the
  adapter's `start()`: an adapter cannot stop what it has not begun, so it would otherwise join and hang until the
  forced cancel.

#### 4.2 Ending when callers leave (`integration/livekit/adapter.py`)

- The listening room also handles `participant_disconnected`. LiveKit removes the participant from
  `remote_participants` before raising it, so `_callers_in(room)` is the callers still there. When the
  leaver is not one of the gateway's own identities and no caller is left, `_stop_event` is set: `start()` returns
  through `_release`, which sends the end-of-session control (3.2).

#### 4.3 The lifecycle contract (`integration/adapter/base.py`)

- `EdgeLifecycleEvent` (dataclass: `session_id`, `start: bool`).
- `EdgeLifecycleAdapter(ABC)`, translation only: `name`, `webhook_path`; abstract `parse(raw) -> EdgeLifecycleEvent | None`
  (verifies and maps one delivery; `None` = starts or ends nothing; raises `HTTPException` to reject) and
  `create_edge(session_id) -> StatefulEdgeAdapter`; `should_start(session_id)` (default `True`). No `verify` or
  `success_response`: no platform needs them, and the host answers `{"status": "ok"}`.

#### 4.4 `EdgeLifecycleRESTRequestHandler` (`integration/adapter/lifecycle.py`)

- The generic host, the sibling of `WebhookRESTRequestHandler`, in its own module so `gateway.py` stays FastAPI-free.
  `RESTRequestHandler`, `requires_pipeline = True`; refuses an adapter with no `webhook_path`.
- `handle`: `parse`; a start with `should_start` true → `_start`; an end → `_stop`; `None` → logged at DEBUG.
  Answers `{"status": "ok"}`.
- `_start`: under a lock, a session already in `_runners` is left alone (a platform may resend a webhook); otherwise
  `_EdgeRunner(adapter.create_edge(session_id))` starts on a thread of its own, kept with the runner in `_runners`.
  The thread removes its own entry when `start()` returns, only if the entry is still that runner. Once
  `ThreadRunner.shutdown_event` is set, no new edge starts.
- `_stop`: `runner.stop()` for the session, if any.
- No shutdown wait: each live edge's `_EdgeRunner` already watches `ThreadRunner.shutdown_event` and stops, and the process does not wait for it. A session whose end control was not sent closes by idle eviction (300 s). `RESTRequestHandler` and `IOHandler` are unchanged.

#### 4.5 `LiveKitLifecycleAdapter` (`integration/livekit/adapter.py`)

- `name = "livekit"`, `webhook_path = "/livekit/webhook"`. `__init__(api_key=None, api_secret=None)`: both default to
  `livekit.api_key`/`api_secret`; missing either raises `ValueError` naming `AK_LIVEKIT__API_KEY`/`AK_LIVEKIT__API_SECRET`.
- `parse`: `api.WebhookReceiver(api.TokenVerifier(key, secret)).receive(body, Authorization)`, so the SDK checks the
  signature while parsing (as Slack's does); any failure is a 401 (`HTTPException` imported in the method, so the
  `livekit` extra needs no FastAPI). `room_started` → `start=True`, `room_finished` → `start=False`, anything else or no room → `None`.
- `create_edge(room)`: `LiveKitEdgeAdapter(session_id=room, api_key=key, api_secret=secret)`,
  so keys passed in code reach the gateway too.

### 5. Consumer changes (AK)

- **`pipeline/realtime_pool.py`:** sections 1.3 and 3.3, 3.4. The `TextDelta`/`AudioDelta` paths are verified unchanged.
- **`framework/adk/adk.py`, `framework/openai/openai.py`:** sections 1.4 and 1.5. Speaker, audio and turn mapping
  are unchanged.
- **`integration/livekit/adapter.py`:** sections 2, 3.2, 4.2 and 4.5.
- **`integration/adapter/base.py`, new `integration/adapter/lifecycle.py`, `integration/adapter/__init__.py`:** 4.3, 4.4 and their lazy exports.
- **`integration/adapter/{base,lifecycle,registry,producer}.py`:** `_enqueue()` with no message (`end_session=True`), the producer stamping it (3.1) and the
  identity-safe `unregister` (3.3); `_EdgeRunner` passes its adapter to `unregister` and gains `stop()` (4.1).
- **`pipeline/io_handler.py`:** drops the `gateways=` parameter and thread loop (4.1); `api/handler.py` is unchanged.
- **`pipeline/response_handler.py`, `pipeline/agent_runner.py`, ECS `akagentrunner.py`:** no change. Verified: both
  realtime runners hand the attributes to `dispatch`, and IOHandler starts `RealtimeAgentRunner` without boot
  gateways in REALTIME mode.
- **`integration/agui/mapping.py`:** no change. `to_agui` returns `None` for an event type with no AG-UI equivalent,
  so `InputTranscript` is dropped there, as `AgentChanged` already is.

### 6. Config changes

**No `AKConfig` changes.** These are class or module constants, each overridable by subclassing or patching:

| Constant | Owner | Value | Why it is not config |
|---|---|---|---|
| `SESSION_END_TIMEOUT_SECONDS` | `LiveKitEdgeAdapter` | 2.0 | Sits beside `PLAYOUT_WAIT_SECONDS` |
| `_RECONNECT_BASE_SECONDS`, `_RECONNECT_MAX_SECONDS` | `realtime_pool` module | 1.0, 30.0 | The back-off after a failed native session (3.4); a safety window, not user behaviour |

### 7. Behavioural changes (AK)

1. **ADK realtime sessions now emit `InputTranscript` chunks with no change to app code**, because ADK transcribes the
   caller by default (1.4). That is one more output message per caller utterance. *Intentional: it is the feature.*
2. **OpenAI realtime sessions emit them once the app turns on transcription** (1.5). *Intentional.*
3. **A bring-your-own edge receives a new event type in `deliver_chunk`.** `StatefulEdgeAdapter.deliver_chunk` is
   abstract, so every edge implements it. An edge that handles only the types it knows (as LiveKit
   does) ignores it with no change. One that rejects unknown types has to ignore it.
   *Intentional, and documented as a contract change for BYO edges.*
4. **A LiveKit edge that stops or loses its room sends an end-of-session control.** The pool closes the native
   session at once, instead of after up to 300 s. *Intentional: it frees model sessions.*
5. **`StatefulEdgeRegistry.unregister` only removes its own adapter** when given one. *Intentional: it prevents a stale
   stop from removing a newer edge.*
6. **A session whose native connection failed is not reopened by the next frame.** Input is dropped for 1, 2, 4... s (at
   most 30 s) after each consecutive failure (3.4). *Intentional: it stops a loop of failing sessions that each sent an
   error to the room and hit the model provider.*
7. **The conversation opens when a participant joins the room**, not when a microphone appears (2). *Intentional: a caller who joins muted is greeted.*
8. **Realtime does not use `framework_context`** in either adapter. *Not a change from base; stated in the contract.*
9. **A LiveKit room gets its own edge and session at runtime** (4.4, 4.5), when the app mounts `EdgeLifecycleRESTRequestHandler(LiveKitLifecycleAdapter())`. *Intentional: it replaces boot-time gateway hosting. `GatewayRunner` and `IOHandler.run(gateways=...)` are removed, so an existing gateway host must migrate to this handler.*
10. **`execute_tool()` and `send_tool_result()` are removed from the `RealtimeRunner` ABC** (the SDK runs its own tools). *Intentional: a bring-your-own realtime runner must drop them.*

**Non-changes:**
- The `StreamChunk` fields.
- The `AgentChanged` shape.
- The `lk-chat` publishing.
- `AKConfig` and its YAML / `AK_*` variables.
- Data written before the change. AK persists nothing new.

