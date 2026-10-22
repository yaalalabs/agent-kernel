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
