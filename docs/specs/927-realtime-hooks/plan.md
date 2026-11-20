# #927: Pre-hooks and post-hooks on realtime calls — Implementation Plan

Order follows risk: first the behaviour-neutral `Runtime` refactor, then the output path (it changes what every call
emits), then the input path, then the small pieces. Section numbers refer to [spec.md](spec.md). Every iteration
leaves the branch passing the existing tests (the ones the spec names are updated in the iteration that changes them).

## Iteration 1: Hook method and Runtime API

- **Goal:** the three public `Runtime` methods and `PreHook.on_stream_input` exist; `run()` and `stream()` behave exactly as before; nothing realtime changes.
- **Files:** `core/hooks.py`, `core/runtime.py`; `tests/test_runtime_hook_api.py` (new).
- **Steps:**
  1. Spec §1: `PreHook.on_stream_input` with the pass-through default and the imports.
  2. Spec §2: rename `_prepare_requests` to `run_pre_hooks` (call sites `core/runtime.py:433`, `:494`).
  3. Spec §2: extract the hook loop of `stream()` (`:521-536`) into `_run_event_chain`; `stream()` calls it and keeps the RunPaused warning (`:538-539`) from its result.
  4. Spec §2: `run_stream_event_hooks` and `run_stream_input_hooks`.
- **Verify:** `cd ak-py && uv run pytest tests/test_runtime_hook_api.py tests/test_runtime.py tests/test_runtime_stream_events.py tests/test_runtime_resume.py tests/test_runtime_resume_warnings.py tests/test_hitl_stream.py` (existing files unchanged and green).

## Iteration 2: Output path

- **Goal:** every output event of a call passes through the post-hooks; `MessageEnd` is sent before `done`; a failing hook ends the call cleanly.
- **Files:** `pipeline/realtime_pool.py`; `tests/test_realtime_hooks.py` (new, output cases), `tests/test_realtime_pool.py`, `tests/test_realtime_edge_path.py`.
- **Steps:**
  1. Spec §3.1: `_hook_context`.
  2. Spec §3.2: `_emit_event`, the `_pacing_loop` changes (events through `_emit_event`, pacing by emitted audio, `MessageEnd` at `done`, `_turn_message_id`), the `StreamHalt` branch.
  3. Spec §3.4: `_fail` skips cancelling the pacing task when called from it.
  4. Update the existing assertions the spec lists: `test_realtime_pool.py:827`, `:851`, `:887` and `test_realtime_edge_path.py:66-77` gain `message_end` before each `done`.
- **Verify:** `uv run pytest tests/test_realtime_hooks.py tests/test_realtime_pool.py tests/test_realtime_edge_path.py tests/test_livekit_edge_adapter.py tests/test_adk_realtime.py tests/test_openai_realtime.py tests/test_ecs_akagentrunner_realtime.py`.

## Iteration 3: Input path

- **Goal:** typed text runs the pre-hooks and caller audio runs `on_stream_input` before the model; hook-made text takes the typed-text path.
- **Files:** `pipeline/realtime_pool.py`; `tests/test_realtime_hooks.py` (input cases), `tests/test_realtime_pool.py`.
- **Steps:**
  1. Spec §3.3: `append_audio` / `send_text` take request objects; `dispatch` passes them (`pipeline/realtime_pool.py:595-599`).
  2. Spec §3.3: `_process_audio` (hooks, resample, adapter send, text items to the text path, first-failure logging) and `_process_text` (`run_pre_hooks`, halt and error chunks, `_last_turn`, one joined send).
  3. Update the callers in tests: `test_realtime_pool.py:729` builds an `AgentRequestVoice`; the `TestDispatchPrincipal._Conn` stub (`:431-447`) takes requests and records `request.prompt`.
- **Verify:** the iteration 2 command, plus a test that a connection with no hooks sends the adapter the same audio and text as before (rate conversion included).

## Iteration 4: Call end and startup warning

- **Goal:** hook state ends with the call; the input-guardrail gap is announced once at startup.
- **Files:** `pipeline/realtime_pool.py`; `tests/test_realtime_hooks.py`.
- **Steps:**
  1. Spec §3.5: `close()` clears the volatile cache after the existing unpublish (`:346-347`).
  2. Spec §3.6: `RealtimeConnectionPool._warn_unchecked_audio`, called from `initialize()` (`:364-369`); the config in its test is a real `_GuardrailConfig`.
- **Verify:** `uv run pytest tests/test_realtime_hooks.py tests/test_realtime_pool.py`.

## Iteration 5: Tests

From spec.md's Testing section: confirm every listed case exists in `tests/test_runtime_hook_api.py` and `tests/test_realtime_hooks.py`, with one assertion list per case and nothing missing; add the gaps. Then:

- `make lint` to format, `make lint-check` for the typing rules (`UP006`, `UP007`, `UP035`, `UP045`); remove by hand any `typing` import ruff leaves unused.
- **Verify:** `cd ak-py && uv run pytest` (full suite).

## Iteration 6: Sync docs and skills

Surfaces the change invalidates (read and located):

- `.agents/skills/ak-dev-architecture/SKILL.md:637` (`.claude/skills` is a symlink to it): "AK pre/post hooks and guardrails do not run on the native path" is false after this change. Describe `on_stream_input`, the three `Runtime` methods, the `MessageEnd` turn end, and the startup warning. Add a line to the Hooks section (`:300-305`) for `on_stream_input`.
- `.agents/skills/ak-dev-testing-conventions/SKILL.md`: its table has no row for the realtime files; add rows for `test_runtime_hook_api.py` and `test_realtime_hooks.py`.
- `docs/docs/integrations/hooks.md`: a "hooks per execution mode" table and a "Realtime calls" section after "Streaming Hooks" (`:210`), including the limits from design.md (captions and audio are separate events, no output guardrail on streamed replies, hooks run on the playback path).
- The statements that hooks do not run on realtime: `docs/docs/architecture/realtime-internals.md:54`, `docs/docs/integrations/livekit.md:231`, `docs/docs/frameworks/openai.md:186`, `docs/docs/frameworks/google-adk.md:216`.
- To check with the sync flows, no update expected: `ak-py/src/agentkernel/skills/ak-add-capabilities/SKILL.md` (its `on_stream_event` example, `:829`, is about SSE); examples' `config.yaml` (no field is added).
- **Steps:** apply the edits, then run `ak-dev-sync-docs-from-branch` and `ak-dev-sync-skills-from-branch` before merge and fix what they report.
- **Verify:** `grep -rn "do not run on the native path\|do not automatically run\|do not run on this path" .agents docs/docs` returns no stale statement.

## Not in this plan

- An example app: it needs model API keys and cannot run in CI. Decide with reviewers.
- Everything in design.md's Non-goals: speech providers, an emit-later handle, ending only a turn on `StreamHalt`, session lock and storage, system tools, tracing.
