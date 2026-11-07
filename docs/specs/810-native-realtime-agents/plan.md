# #810: Native realtime agents and handoffs — Implementation Plan

Build the [design](design.md) using the component contracts and limits in [spec.md](spec.md). Each iteration should leave a runnable, testable path. Do not replace native SDK behavior with another AK tool, transfer, or socket engine.

## Iteration 1: OpenAI native live session

- **Goal:** A `RealtimeAgent` can receive text/audio and hand off A → B → A through the OpenAI Agents SDK, while the existing pool still carries output.
- **Files:** `ak-py/src/agentkernel/core/realtime/runner.py`, `ak-py/src/agentkernel/framework/openai/openai.py`; `ak-py/tests/test_openai_runner.py` or new `ak-py/tests/test_openai_realtime.py`.
- **Steps:**
  1. Narrow the `RealtimeRunner` ABC: remove the two abstract tool methods and add the default speaker hook (spec: **`RealtimeRunner` contract**). The old ADK adapter may still provide its extra methods until iteration 2.
  2. Replace the raw-socket `OpenAIRealtimeRunner` with native `RealtimeRunner`/`RealtimeSession` (spec: **OpenAI adapter**). Keep its existing AK callback boundary.
  3. Map native SDK events to AK audio, text, speaker, interruption, completion, and error events in order. Use native tools and handoffs; remove the adapter's manual tool/transfer/replay code.
  4. Preflight ordinary `Agent`, approval tools, and bad native options.
  5. Use the SDK default playback estimate. Test a handoff back to the original agent, a separate native tool on each agent, and barge-in behavior. Keep unary OpenAI tests green.
- **Verify:** `cd ak-py && uv run pytest tests/test_openai_runner.py` (plus `tests/test_openai_realtime.py` if created). Check the SDK's public event fields against the pinned optional extra; raise the minimum dependency only if needed.

## Iteration 2: ADK native live run

- **Goal:** One ADK `run_live()` call and one `LiveRequestQueue` serve a call that transfers A → B → A; ADK runs its declared tools.
- **Files:** `ak-py/src/agentkernel/framework/adk/adk.py`, `ak-py/pyproject.toml`; `ak-py/tests/test_adk_runner.py` or new `ak-py/tests/test_adk_realtime.py`.
- **Steps:**
  1. Replace `GoogleADKRealtimeRunner`'s direct Gemini socket with ADK `Runner.run_live()` and `LiveRequestQueue` (spec: **ADK adapter**). Reuse the per-session ADK session service; remove copied tool/transfer/replay logic.
  2. Map caller audio/text into the queue and map ADK event authors to speaker changes. Pass `RunConfig` and supported runner options to their native destinations.
  3. Accept a native graph `Workflow` as a live root. Reject unsupported graph modes, confirmation requests, and bad options. Close the queue and live generator on failed startup or normal stop.
  4. Raise `google-adk` to `>=2.7.0` for the transfer ordering fix. Measure refused or invalid transfer behavior at that minimum version when the version is available. Keep unary ADK tests green.
- **Verify:** `cd ak-py && uv run pytest tests/test_adk_runner.py` (plus `tests/test_adk_realtime.py` if created). Run the minimum-version transfer tests in a separate environment with `google-adk==2.7.0`; record the result.

## Iteration 3: Narrow the AK realtime boundary

- **Goal:** The pool handles audio and queue delivery only. A BYO runner's old `tool_call` fails clearly; speaker events select the correct LiveKit participant.
- **Files:** `ak-py/src/agentkernel/pipeline/realtime_pool.py`, `ak-py/src/agentkernel/integration/livekit/adapter.py` only if the current speaker/roster behavior needs a change; `ak-py/tests/test_realtime_pool.py`, `ak-py/tests/test_livekit_gateway.py`.
- **Steps:**
  1. Remove the pool tool task (spec: **Realtime pool**). Fail on `tool_call` and unknown callbacks; remove the temporary old callback documentation left during adapter migration.
  2. Keep paced output and interruption queue clearing. Do not add a queue-delivery hook for OpenAI's playback tracker; actual LiveKit playout is not acknowledged by this boundary.
  3. Make failed connection startup close native resources and avoid removing a newer registry entry. Keep per-session isolation and existing send/eviction bounds.
  3a. Set `ToolContext`, `Session.current()` and `Agent.current()` once in `RealtimeConnection.connect()` around `adapter.connect()`, so the SDK's tasks inherit them (spec: **Realtime pool**); attach AK system tools in realtime mode as in every other mode; reject an ADK `FunctionTool` that requires confirmation before opening (spec: **ADK adapter**, step 6).
  4. Handle a non-speaking ADK `Workflow` root: publish the first actual speaking author and declared team before its output. Verify LiveKit still filters its own participants and mutes the previous speaker before the next one's audio.
- **Verify:** `cd ak-py && uv run pytest tests/test_realtime_pool.py tests/test_livekit_gateway.py`. A fake BYO runner emitting `tool_call` must produce one terminal error chunk and no tool execution.

## Iteration 4: Cross-boundary tests and live checks

- **Goal:** Prove the two SDK adapters, pool, queue consumer, and LiveKit gateway work as one path; close any gap found by those tests.
- **Files:** `ak-py/tests/test_realtime_pool.py`, `ak-py/tests/test_openai_runner.py` / `test_openai_realtime.py`, `ak-py/tests/test_adk_runner.py` / `test_adk_realtime.py`, `ak-py/tests/test_livekit_gateway.py`, `ak-py/tests/test_ecs_akagentrunner_realtime.py`, relevant tool-builder tests.
- **Steps:**
  1. Cover A → B → A, each agent's native tool, speaker-before-audio order, text, voice, barge-in, guardrail interruption, approval/confirmation failure, MCP pass-through or explicit SDK rejection, custom-runner break, cleanup, and two-session isolation (spec: **Testing**).
  2. Verify native tools still run after handoffs.
  3. Update old tests that patch raw sockets or pool `execute_tool` to patch `agentkernel.framework.openai.openai.RealtimeRunner`/`RealtimeSession` and `agentkernel.framework.adk.adk.Runner.run_live`/`LiveRequestQueue` instead. Keep queue transport fakes at `QueueTransportFactory.create`.
  4. Run a credentialed OpenAI and ADK LiveKit example only where keys and a room are available; record SDK versions, handoff order, and any model-specific limits. Deterministic tests remain the required local gate.
  5. Record whether ADK's experimental `LiveKitRunner` can preserve AK queue routing and a separate room participant per active agent. Keep the existing shared AK edge unless those requirements are shown with a working test.
- **Verify:** `cd ak-py && uv run pytest tests/test_realtime_pool.py tests/test_openai_runner.py tests/test_adk_runner.py tests/test_livekit_gateway.py tests/test_ecs_akagentrunner_realtime.py` plus the new focused files if created. Then run `make lint-check-all` from the repo root.

## Iteration 5: Sync examples, docs, and skills

- **Goal:** A new user can build a live multi-agent room from the examples without reading the old custom-runner behavior.
- **Files:** `examples/api/livekit-voice/openai/{in_memory,handoffs}/server.py` and READMEs; `examples/api/livekit-voice/google/{in_memory,handoffs}/server.py` and READMEs; their lockfiles if the dependency floor changes; `examples/api/livekit-voice/README.md`; `docs/docs/architecture/realtime-internals.md`; `docs/docs/integrations/livekit.md`. Check the other LiveKit example servers/READMEs and `README.md` / `ak-py/README.md` for claims invalidated by this change.
- **Steps:**
  1. Move OpenAI examples to `RealtimeAgent` and native session model/voice settings. Move ADK per-agent voice to `Gemini(speech_config=...)`; show `mode='chat'` or `mode='task'` when a speaking workflow node is used.
  2. Rewrite diagrams and descriptions that say AK opens raw sockets, executes tools, or replays transcripts. Add the spec's separate OpenAI/ADK support list and the `tool_call` break for BYO runners. State that AK queue delivery does not measure actual LiveKit playout, that AK hooks and guardrails do not run there, and that the OpenAI/ADK wrappers skip AK system tools and their guidance in realtime mode.
  3. Check `.agents/skills/ak-dev-architecture/SKILL.md`, `ak-dev-testing-conventions/SKILL.md`, and `ak-dev-new-framework-integration/SKILL.md` for stale realtime guidance. The current scan found no named realtime runner references there; leave them unchanged if a final scan confirms that. Do not edit bundled end-user skills unless a shipped instruction actually describes the old realtime behavior.
  4. Follow `ak-dev-sync-docs-from-branch` and `ak-dev-sync-skills-from-branch` before merge. The docs landing/features inventories need no new entry because OpenAI, ADK, and LiveKit already exist; recheck hard-coded claims, and never edit `docs/versioned_docs/`.
- **Verify:** Run the example imports or startup validation without opening billable live calls, inspect the changed docs for old claims with scoped `rg`, and rerun `make lint-check-all`. Confirm the final diff contains only the intended source, tests, examples, and current docs/skills.


## Edge additions for realtime calls (C1 to C6)

### Iteration 1: The caller's words as an event (C1)

- **Goal:** Both adapters report the caller's finished utterance, and it reaches the edge in spoken order.
- **Files:**
  - `ak-py/src/agentkernel/core/event.py`: the `InputTranscript` event, added to the `StreamEvent` union.
  - `ak-py/src/agentkernel/core/realtime/runner.py`: document the `input_transcript` callback in `connect()`.
  - `ak-py/src/agentkernel/pipeline/realtime_pool.py`: accept `input_transcript` in `handle_framework_event` and emit
    it from `_pacing_loop`.
  - `ak-py/src/agentkernel/framework/adk/adk.py`: map a finished `input_transcription` on a user-authored event,
    before the early return at `:1112`.
  - `ak-py/src/agentkernel/framework/openai/openai.py`: map `input_audio_transcription_completed` in
    `_handle_model_event` (`:805`).
  - `ak-py/src/agentkernel/integration/livekit/adapter.py`: accept the new event in `deliver_chunk` and ignore it for
    now.
- **Steps:**
  1. Add the event and the callback name.
  2. In the pool, queue it behind output, and keep it through a barge-in (spec §1.3, rule 1).
  3. Map it in both adapters (spec §1.4, §1.5). Partial ADK transcription is not reported, only finished lines.
  4. Add `InputTranscript` to `ALL_EVENTS` in `tests/test_stream_events.py`. Its union-coverage guard fails otherwise.
- **Verify:**

  ```bash
  cd ak-py && uv run pytest tests/test_stream_events.py tests/test_adk_realtime.py tests/test_openai_realtime.py tests/test_realtime_pool.py
  ```

  The new tests check one `InputTranscript` per scripted utterance, before the reply that answers it, for each SDK.

### Iteration 2: Live captions, opening prompt (C2, C5)

- **Goal:** The room gets live captions for every speaker, a stalled caption write cannot stop the ones after it, and
  the opening prompt can be changed. A caller who joins muted is greeted.
- **Files:**
  - `ak-py/src/agentkernel/integration/livekit/adapter.py`: captions, the caption write bound, the caller identity taken
    when a caption is queued, the opening-prompt method that replaces the fixed text, and `_on_participant_connected`
    (spec §2).
- **Steps:**
  1. Use LiveKit's caption names from spec §2.2, through `local_participant.stream_text(...)` / `send_text(...)`, which
     exist in `livekit` 1.1.20. Check against a real LiveKit server that `sender_identity` for the caller's caption is
     accepted.
  2. Stream agent text deltas from the speaking participant as they are paced. Send the caller's line attributed to the
     caller, with the identity it was heard from.
  3. Perform captions on one task per gateway, each write bounded by `CAPTION_WRITE_TIMEOUT_SECONDS`.
  4. Keep the turn-end `lk-chat` message as it is.
  5. Add the opening-prompt method. Its default returns today's text without "microphone", and `None` sends nothing.
     Open the conversation when a participant joins the room, and greet a caller already in the room when the gateway
     joins (LiveKit raises `participant_connected` only for later joins).
  6. Bind the first participant to the starting agent only; an agent a later change names first joins as its own.
- **Verify:**

  ```bash
  cd ak-py && uv run pytest tests/test_livekit_gateway.py
  ```

  The tests cover:
  - captions from the right participant, one stream per segment, one final message;
  - a barge-in: the interrupted segment ends with what was delivered;
  - a stalled caption write: skipped, and the captions after it still go out;
  - a caller caption keeps the identity the line was heard from;
  - the opening prompt: `None`, custom, and the default; a participant who joins muted is greeted.

### Iteration 3: Gateways at runtime, end a session at once (C3, C4)

- **Goal:** Many calls in one process. Each gateway starts and stops on demand, and ending one closes its model session
  at once.
- **Files:**
  - `ak-py/src/agentkernel/integration/adapter/base.py`: `_mark_ready` / `wait_ready` and `_enqueue_end` (spec §3.1,
    §4.2).
  - `ak-py/src/agentkernel/integration/adapter/gateway.py`: `start_background`, `stop` and `running` (spec §3.2).
  - `ak-py/src/agentkernel/integration/adapter/registry.py`: an identity-safe `unregister`, and `recently_ended`
    (spec §3.3).
  - `ak-py/src/agentkernel/integration/adapter/producer.py`: `enqueue(..., attributes=)` (spec §4.1).
  - `ak-py/src/agentkernel/pipeline/envelope.py`: `ATTR_REALTIME_END` (spec §4.1).
  - `ak-py/src/agentkernel/integration/livekit/adapter.py`: `_mark_ready` on connect, and `_send_session_end` in
    `_release` (spec §4.2).
  - `ak-py/src/agentkernel/pipeline/realtime_pool.py`: `end_session` and the ended-session TTL (spec §4.3).
  - `ak-py/src/agentkernel/pipeline/response_handler.py`: drop trailing chunks for a recently ended edge (spec §4.4).
- **Steps:**
  1. Readiness on the edge, then `start_background` / `stop` on `GatewayRunner`. A background failure is re-raised to
     the caller and never ends the process.
  2. Registry: an identity-safe unregister, plus the recently-ended marks.
  3. Producer extra attributes, then the control send in `_release`: stop staging, drain `_pending` (no control if input is
     still unsent after `SESSION_END_TIMEOUT_SECONDS`), send the control, bounded by the same time.
  4. Pool `end_session` and the TTL drop, keyed by the edge instance id (`edge_id` in the reply context) so a new edge for
     the same session id is a new call, then the Response Handler's quiet drop.
  5. A failed connect sends the edge one terminal error chunk (`fail_to_connect`), since the back-off drops its redelivery.
- **Verify:**

  ```bash
  cd ak-py && uv run pytest tests/test_integration_gateway_runner.py tests/test_realtime_pool.py tests/test_livekit_gateway.py \
    tests/test_pipeline_response_handler.py tests/test_integration_producer.py
  ```

  The tests are the C3 and C4 cases listed in spec "Testing".

### Iteration 4: AK tests and lint

- **Goal:** The additions work together through the whole path, and nothing older breaks.
- **Files:** the test files above, plus `ak-py/tests/test_ecs_akagentrunner_realtime.py` (the ECS realtime path must
  still pass).
- **Steps:**
  1. Run one path with a fake native session: a caller line, a handoff, the agent's reply, then end-of-session. Check
     the chunk order and each agent's chat message.
  2. Check that the existing LiveKit examples still import and start validation without credentials.
- **Verify:**

  ```bash
  cd ak-py && uv run pytest tests/test_realtime_pool.py tests/test_openai_realtime.py tests/test_adk_realtime.py \
    tests/test_livekit_gateway.py tests/test_integration_gateway_runner.py tests/test_ecs_akagentrunner_realtime.py
  make lint-check-all   # from the repo root
  ```

