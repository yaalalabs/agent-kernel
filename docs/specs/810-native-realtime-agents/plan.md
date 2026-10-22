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
