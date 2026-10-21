# #810: Realtime multi-agent collaboration — Implementation Plan

> OpenAI native-engine extension: earlier statements that OpenAI is unchanged are
> superseded by [the migration research](research/openai-native-realtime.md) and the
> “OpenAI native realtime extension” in design.md. Voice declarations use RealtimeAgent;
> the SDK owns execution, and the shared pool receives paced-audio tracking notifications.


This plan builds [`spec.md`](spec.md) in order: the core contracts first, then the Gemini adapter, the pool, recovery,
the LiveKit gateway, the example, the tests, and the docs and skills sync. Each iteration leaves the branch importable,
lint-clean and its suite green. Work happens on `feature/realtime-multi-agent-collaboration` off `develop`; the PR is
#818, titled `feat: realtime multi-agent collaboration (#810)`. The spec documents are committed before the code they
describe.

Revised: the background jobs (`RealtimeCall.run_in_background` and its hosting) and OpenAI realtime tool input
guardrails were built and then removed from this PR (design.md "Open questions"); the iterations below describe what
remains, with research and review in the application as awaited tools.

Revised: iterations 2, 4 and 6 built a Gemini adapter that drove Gemini Live itself and re-implemented ADK's tool
callbacks, history and recovery. Iteration 17 replaces them with ADK's own live engine; they are kept below as built,
marked superseded. Likewise the outbox of iterations 5 and 11: iteration 18 replaces it with a guarded send, the
application keeping what waits.

## Iteration 1: Core contracts

- **Goal:** realtime observers and the new adapter events exist in `core/`; nothing uses them yet.
- **Files:** `ak-py/src/agentkernel/core/realtime/observer.py`, `core/realtime/__init__.py`, `core/__init__.py`, `core/realtime/runner.py`
- **Steps:**
  1. Add `RealtimeEvent` and `RealtimeObserver`, per spec.md "Core contracts".
  2. Add `RealtimeRunner.reports_speech_stopped` and document every new adapter event in the callback contract, `reconnected` and the `reconnecting` status included (Rule 2).
- **Verify:** `cd ak-py && uv run pytest tests/test_realtime_pool.py`.

## Iteration 2: ADK tool callbacks (superseded by Iteration 17)

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

## Iteration 4: Authored history and Live settings (superseded by Iteration 17)

- **Goal:** a transfer's seed shows who said what, and every socket uses the call's `RunConfig`.
- **Files:** `adk.py`
- **Steps:**
  1. Keep `_Said` entries and seed through `_presented_history()`, per spec.md "Authored history".
  2. Read the `run_config` run option at connect and set turn detection and transcription in `_connect_config`, per spec.md "Live settings".
- **Verify:** `TestADKRealtimeTransfers`, `TestADKConnectConfig`.

## Iteration 5: Talking into a live call and realtime observers

- **Goal:** application code posts into a call at a quiet moment and watches it through observers.
- **Files:** `realtime_pool.py`, `ak-py/src/agentkernel/pipeline/__init__.py`
- **Steps:**
  1. Add `RealtimeOutbox` and its delivery from the pool's loop, with every state write under its lock (superseded by Iteration 18).
  2. (`post_when_idle` and `withdraw` superseded by Iteration 18.) Add the pool's `post_when_idle`, `withdraw` and `close`, its lookups (`open_connection`, `live_connection`, `outbox`), and `RealtimeCall` reading the call's facts through them; export `RealtimeCall`.
  3. Add `RealtimeCall.observe` / `unobserve` and the observer queue and task, per spec.md "Observers".
  4. Add the loop-lag warning, and make the sweep close failed connections, per spec.md "Sweep and loop lag".
- **Verify:** `TestRealtimeOutbox`, `TestRealtimeCall`, `TestRealtimeObservers`, the sweep and loop-lag tests.

## Iteration 6: Connection recovery (superseded by Iteration 17)

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

- **Goal:** `examples/api/livekit-voice/google/handoffs/` shows a refused handoff, a booking that waits for the dispatch system, and the call log, and its offline tests run in CI.
- **Files:** `examples/api/livekit-voice/google/handoffs/{server.py,server_test.py,README.md}`, `.github/test-config.yaml`
- **Steps:**
  1. Add `verify_account`, `require_account`, the awaited confirmation in `book_technician` and `CallLog`, and build the gateway under `__main__`, per the spec.md "Example" table.
  2. Write `server_test.py` per spec.md "New: `examples/api/livekit-voice/google/handoffs/server_test.py`".
  3. Build ak-py (`ak-py/build.sh`), then run `./build.sh local` in the example; register it in `.github/test-config.yaml`.
- **Verify:** `cd examples/api/livekit-voice/google/handoffs && uv run pytest -s` passes offline; with a LiveKit room and a Gemini key, a call shows the refused handoff, the confirmed booking and the call log.

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

## Building blocks for applications

Iterations 11 to 16 build spec.md "Application building blocks", in the same PR, each leaving the suite green.

## Iteration 11: Call facts and `while_quiet` (the outbox part superseded by Iteration 18)

- **Goal:** application code reads the call's facts and acts on a quiet call, with no thread of its own.
- **Files:** `pipeline/realtime_pool.py`
- **Steps:** the facts; `_quiet_since`; `while_quiet` (spec.md "Call facts").
- **Verify:** `TestRealtimeCallFacts`, `TestRealtimeOutbox`, `TestRealtimeOutboxWhileQuiet`.

## Iteration 12: Tool calls the connection owns

- **Goal:** a tool that awaits long work keeps the call busy, answers through its own call, and is cancelled when its call closes, sending nothing late.
- **Files:** `pipeline/realtime_pool.py`, `ak-py/tests/test_realtime_pool.py`
- **Steps:** spec.md "Tool calls the connection owns" Rules 1 to 4: `_tool_tasks`, `_cancel_tools()` in `close()`, no result once `closed`.
- **Verify:** `TestRealtimeAwaitedTools` (failing with the cancellation and the closed check taken out); the stall case in `TestADKRealtimeRecovery`.

## Iteration 13: Gateways per session

- **Goal:** a gateway stops on its own, so an application can host one per session.
- **Files:** `integration/adapter/gateway.py`, `integration/adapter/__init__.py`
- **Steps:** `GatewayRunner.stop` (spec.md "Gateways").
- **Verify:** `test_integration_gateway_runner.py`.

## Iteration 14: Example, docs and skills

- **Goal:** the example's booking is an awaited tool; the docs and skills describe the building blocks.
- **Files:** `examples/api/livekit-voice/google/handoffs/{server.py,server_test.py,README.md}`, the surfaces in spec.md "Migration surface"
- **Steps:** switch `book_technician` (spec.md "Example"); update the tests; edit the docs and the two dev skills.
- **Verify:** the example's `uv run pytest -s`; `cd docs && npm run build`; the full suite and `make lint-check-all`.

## Iteration 15: The pool's module

- **Goal:** the pool stays in `pipeline/realtime_pool.py`, its 0.9.5 path, with no `pipeline/realtime/` package.
- **Files:** `pipeline/realtime_pool.py`, `pipeline/__init__.py`, `pipeline/agent_runner.py`, `deployment/aws/containerized/akagentrunner.py`, the tests' imports
- **Steps:** spec.md "Module layout".
- **Verify:** `from agentkernel.pipeline.realtime_pool import RealtimeConnectionPool` works and its patch targets reach the pool; the full suite.

## Iteration 16: The application (outside this repository)

- **Goal:** the application that drove the change runs on the building blocks: research and review as awaited voice tools running their agents through `AgentService` in sessions of their own (failure detected natively, as before), its nudges a task polling `RealtimeCall.quiet_for()` that its observer runs per connection, its rooms one `GatewayRunner` each, its handoff rules one policy class on ADK's callbacks.
- **Verify:** its tests pass, against a fresh AK build; a live call: handoffs, research and a review (how long the caller waits), a refused handoff, a nudge, the meeting ended while research runs.

## Iteration 17: Google ADK on its own live engine

- **Goal:** the Gemini adapter runs each call on ADK's `Runner.run_live`; ADK owns tools, callbacks, plugins, transfers,
  history and session resumption, and AK keeps only the tool scope, event reporting and restarting a failed run.
- **Files:** `core/realtime/runner.py`, `pipeline/realtime_pool.py`, `framework/adk/adk.py`, `ak-py/pyproject.toml`,
  `ak-py/uv.lock`, `examples/api/livekit-voice/google/handoffs/server.py`, `ak-py/tests/test_adk_realtime.py`,
  `ak-py/tests/test_realtime_pool.py`
- **Steps:**
  1. Add `runs_tools` and `use_tool_scope()` to `RealtimeRunner`, and `open_tool_scope()` to the pool, per spec.md
     "Core contracts" Rule 5.
  2. Rewrite `GoogleADKRealtimeRunner` on `Runner.run_live`, per spec.md "ADK realtime runner": the tool scope plugin
     first, the starting agent's Runner options and `RunConfig`, the event table, the restart and stall rules.
  3. Remove the manual callbacks, transfers, history, socket handling and held input, and their tests.
  4. Raise the `adk` extra to `google-adk>=2.7.0`, checked by running `test_adk_realtime.py` on 2.6.0 and 2.7.0.
  5. Move each agent's voice to its model (`Gemini(model=..., speech_config=...)`) in the example.
- **Verify:** `test_adk_realtime.py` on ADK 2.7.0, 2.8.0 and 2.11.0; `TestRealtimeToolScope`; the full suite;
  `make lint-check-all`; a live call through the driving application.

## Iteration 18: A guarded send instead of an outbox

- **Goal:** AK keeps the delivery mechanics and the application the scheduling: no queue of application text in AK.
- **Files:** `pipeline/realtime_pool.py`, `ak-py/tests/test_realtime_pool.py`; in the driving application, its call
  link, the meeting's end, and their tests
- **Steps:**
  1. Move the quiet rule onto `RealtimeConnection` (`awaiting_reply`, `quiet_since`, `last_post_at`), the owed reply
     named as an inference, and add `send_if_quiet`, per spec.md "The quiet rule and the guarded send".
  2. Add `RealtimeCall.send_if_quiet` and `quiet_since`, running the send on the pool's loop from any loop.
  3. Remove `RealtimeOutbox`, `post_when_idle`, `withdraw`, the pool's outboxes and their delivery; the loop's tick is
     `_TICK_SECONDS`.
  4. In the application: what waits (keys, expiry, a bounded list, the stretch a nudge is for) per call, under a lock,
     tried by its watch on the realtime loop; cleared when the meeting ends.
- **Verify:** `TestRealtimeQuietCall`, `TestRealtimeCall`, `TestRealtimeAwaitedTools`; the application's delivery tests;
  the full suite; a live call (nudges, approval and project updates, the renewal notice).

