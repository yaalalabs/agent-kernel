# #810: Realtime multi-agent collaboration with background work — Implementation Plan

This plan builds [`spec.md`](spec.md) in order: the core contracts first, then the Gemini adapter, the pool, recovery,
the LiveKit gateway, the example, the tests, and the docs and skills sync. Each iteration leaves the branch importable,
lint-clean and its suite green. Work happens on `feature/realtime-multi-agent-collaboration` off `develop`; the PR is
#818, titled `feat: realtime multi-agent collaboration with background work (#810)`. The spec documents are committed
before the code they describe.

## Iteration 1: Core contracts

- **Goal:** realtime hooks and the new adapter events exist in `core/`; nothing uses them yet.
- **Files:** `ak-py/src/agentkernel/core/hooks.py`, `core/base.py`, `core/module.py`, `core/__init__.py`, `core/realtime/runner.py`
- **Steps:**
  1. Add `RealtimeEvent`, `RealtimeHook`, `Agent.realtime_hooks` and `Module.realtime_hook`, per spec.md "Core contracts".
  2. Add `RealtimeRunner.reports_speech_stopped` and document every new adapter event in the callback contract, `reconnected` and the `reconnecting` status included (Rule 2).
- **Verify:** `cd ak-py && uv run pytest tests/test_module.py`.

## Iteration 2: ADK tool callbacks

- **Goal:** realtime ADK tool calls run the agent's tool callbacks.
- **Files:** `ak-py/src/agentkernel/framework/adk/adk.py`
- **Steps:**
  1. Add `_run_tool` and `_call`, and call `_run_tool` from `execute_tool`, per spec.md "Tool callbacks".
- **Verify:** `TestADKRealtimeToolCallbacks` in `test_realtime_pool.py`.

## Iteration 3: Caller events and turn state

- **Goal:** both adapters report the caller's turns, and each connection keeps its turn state.
- **Files:** `adk.py`, `ak-py/src/agentkernel/framework/openai/openai.py`, `ak-py/src/agentkernel/pipeline/realtime_pool.py`, `ak-py/tests/test_ecs_akagentrunner_realtime.py`
- **Steps:**
  1. Report `speech_started`, `speech_heard` and `caller_transcript` from the ADK adapter, per spec.md "Caller turn events".
  2. Report `speech_stopped` from the OpenAI adapter.
  3. Keep the turn state on `RealtimeConnection`, per the spec.md "Turn state" table, and pass `from_edge=True` from `dispatch`.
- **Verify:** `TestRealtimeTurnState`, `TestADKRealtimeSpeechStarted`, `TestADKCallerTranscript`, `TestOpenAIBargeIn`; `test_ecs_akagentrunner_realtime.py`.

## Iteration 4: Authored history and Live settings

- **Goal:** a transfer's seed shows who said what, and every socket uses the call's `RunConfig`.
- **Files:** `adk.py`
- **Steps:**
  1. Keep `_Said` entries and seed through `_presented_history()`, per spec.md "Authored history".
  2. Read the `run_config` run option at connect and set turn detection and transcription in `_connect_config`, per spec.md "Live settings".
- **Verify:** `TestADKRealtimeTransfers`, `TestADKConnectConfig`.

## Iteration 5: Talking into a live call and realtime hooks

- **Goal:** application code posts into a call at a quiet moment and watches it through hooks.
- **Files:** `realtime_pool.py`, `ak-py/src/agentkernel/pipeline/__init__.py`
- **Steps:**
  1. Add `RealtimeOutbox` and its delivery from the pool's loop, per spec.md "Outbox", with every state write under its lock.
  2. Add the pool's `post_when_idle`, `withdraw`, `close`, `is_connected`, `quiet_for`, `agent_has_spoken`, and `RealtimeCall` over them; export `RealtimeCall`.
  3. Add the hook queue and task, per spec.md "Hooks".
  4. Add the loop-lag warning, and make the sweep close failed connections, per spec.md "Sweep and loop lag".
- **Verify:** `TestRealtimeOutbox`, `TestRealtimeCall`, `TestRealtimeHooks`, the sweep and loop-lag tests.

## Iteration 6: Connection recovery

- **Goal:** a lost or stalled Gemini socket reconnects the same agent by replaying the conversation, and a recovering call takes no post.
- **Files:** `adk.py`, `realtime_pool.py`
- **Steps:**
  1. Add the recovery constants, `_recover_soon`, `_recover` (steps 1 to 4, and the replay of step 5) and the stall watchdog, per spec.md "Recovery".
  2. Pass the replay note to `_open_socket` as `extra`, so it never enters `_history`.
  3. Keep `_lost_batches` and record their late results, per Rule 1.
  4. Apply the stall wait of Rule 2 and the held input of Rule 3; cancel both tasks in `disconnect()` (Rule 4).
  5. Report `reconnected` with `seeded`; in the pool, mark the connection recovering between `reconnecting` and `reconnected`, and count a seeded reconnect as owed a reply, per the "Turn state" table and "Outbox" step 3.
- **Verify:** `TestADKRealtimeRecovery` (the replay cases), `TestRealtimeTurnState` (recovering), `TestRealtimeOutbox` (a seeded reconnect).

## Iteration 7: LiveKit tokens and alias

- **Goal:** an application signs its users' tokens through the gateway and imports it by its public name.
- **Files:** `ak-py/src/agentkernel/integration/livekit/adapter.py`, `ak-py/src/agentkernel/livekit.py` (new), `examples/api/livekit-voice/**`
- **Steps:**
  1. Add `AGENT_IDENTITY_PREFIX`, `participant_token` and `_sign`, per spec.md "LiveKit gateway".
  2. Add the alias; switch the LiveKit examples to the public aliases and the `sqs` token handlers to `participant_token`.
- **Verify:** `cd ak-py && uv run pytest tests/test_livekit_gateway.py`.

## Iteration 8: Example

- **Goal:** `examples/api/livekit-voice/google/handoffs/` shows a refused handoff, a background post and the call log, and its offline tests run in CI.
- **Files:** `examples/api/livekit-voice/google/handoffs/{server.py,server_test.py,README.md}`, `.github/test-config.yaml`
- **Steps:**
  1. Add `verify_account`, `require_account`, the background confirmation in `book_technician` and `CallLog`, and build the gateway under `__main__`, per the spec.md "Example" table.
  2. Write `server_test.py` per spec.md "New: `examples/api/livekit-voice/google/handoffs/server_test.py`".
  3. Build ak-py (`ak-py/build.sh`), then run `./build.sh local` in the example; register it in `.github/test-config.yaml`.
- **Verify:** `cd examples/api/livekit-voice/google/handoffs && uv run pytest -s` passes offline; with a LiveKit room and a Gemini key, a call shows the refused handoff, the dispatch post and the call log.

## Iteration 9: Tests

- **Goal:** every case in spec.md "Testing" exists and passes, the whole suite is green, and the live check holds.
- **Steps:**
  1. Fill any case from spec.md "Testing" that an iteration above did not add.
  2. Run the spec.md "Commands".
  3. Do the live check with the maintainer's keys, per spec.md "Live check".
- **Verify:** every command exits 0; in CI, the only red jobs are e2e jobs that also fail on `develop`.

## Iteration 10: Sync docs and skills

- **Goal:** every surface in spec.md "Migration surface" describes the change as built.
- **Files:** everything in spec.md "Migration surface"
- **Steps:**
  1. Edit each surface; re-check line numbers first, because they drift.
  2. Run the `ak-dev-sync-docs-from-branch` and `ak-dev-sync-skills-from-branch` flows to confirm nothing else drifted.
  3. Write the PR description from `design.md`: the change, the resolved questions, `Relates to #810`; leave out what #808 already merged (ADK `transfer_to_agent`, LiveKit agent participants). Answer each open review thread with the commit that addresses it, and the browser-edge threads by pointing to its removal.
- **Verify:** `cd docs && npm run build` succeeds; the two sync flows report no drift.
