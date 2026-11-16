# #928: Realtime calls follow the AK run lifecycle: session, context and tracing — Implementation Plan

Builds [spec.md](spec.md) in four iterations. Each one leaves the branch green. Start from `feature/927-realtime-hooks`
(or `develop` once #927 and #941 have merged), on a `feature/928-...` branch.

## Iteration 1: Store the session

- **Goal:** a call stores its session once, when it ends normally, as `Runtime.stream` does; the write runs off the pool loop.
- **Files:** `pipeline/realtime_pool.py`, `tests/test_realtime_session_store.py` (new).
- **Steps:**
  1. In `RealtimeConnection`: `_failed` set by `_fail` and `fail_to_connect`; `_store_session()`; the `close()` order: disconnect, store unless failed, then clear the identity and the volatile cache (spec 2.2).
  2. `tests/test_realtime_session_store.py` (spec Testing).
- **Verify:** `uv run pytest tests/test_realtime_session_store.py tests/test_realtime_pool.py tests/test_realtime_hooks.py tests/test_realtime_edge_path.py tests/test_ecs_akagentrunner_realtime.py`.

## Iteration 2: Trace a call

- **Goal:** with `trace.enabled`, each realtime call has one AK span tagged with the session id; text mode is unchanged.
- **Files:** `trace/base.py`, `trace/trace.py`, `trace/otel.py` (new), `trace/{langfuse,openllmetry,logfire,cloudwatch}/` (`<provider>.py`, `openai.py`, `adk.py`), `framework/openai/openai.py`, `framework/adk/adk.py`, `tests/test_trace_realtime.py` (new), `tests/test_trace_cloudwatch.py`, `tests/test_trace_logfire.py`.
- **Steps:**
  1. `RealtimeCallSpan`, `TracedRealtimeRunner` and the two optional `BaseTrace` methods; `Trace` delegation (spec 3.1).
  2. `OTelRealtimeCallSpan` (spec 3.2).
  3. Per provider: the call span (langfuse, openllmetry, cloudwatch), the two runner classes, `openai_realtime()` / `adk_realtime()` (spec 3.3).
  4. The selection in both modules (spec 3.4).
- **Verify:** `uv run pytest tests/test_trace_realtime.py tests/test_trace.py tests/test_trace_cloudwatch.py tests/test_trace_logfire.py tests/test_trace_langfuse_flush.py tests/test_openai_realtime.py tests/test_adk_realtime.py tests/test_module.py`.

## Iteration 3: Tests across the change

- **Goal:** the end-to-end guarantees are pinned.
- **Files:** `tests/test_realtime_system_tools.py` (new).
- **Steps:**
  1. Turn the design's experiment into `tests/test_realtime_system_tools.py`: the real `create_schedule` in a live call on both SDKs, for a caller, no principal, and a principal changed between inputs through `dispatch` (spec Testing).
  2. Add the ADK nesting case to `tests/test_trace_realtime.py`: ADK's `invoke_agent` span is a child of a call span opened only around `connect`, using a local `TracerProvider` (never a global one).
  3. Full suite and lint.
- **Verify:** `cd ak-py && uv run pytest`, then `make lint-check`.

## Iteration 4: Sync docs and skills

- **Docs:**
  - `docs/docs/integrations/livekit.md:160` and `docs/docs/architecture/realtime-internals.md:52`: the AK session is stored when a call ends normally; `framework_context` is still not carried. Add the scheduling limit to `livekit.md`.
  - `docs/docs/advanced/traceability.md`: a realtime section (the call span per provider, ADK's native spans as its children, what the OpenAI instrumentor adds, the Langfuse session-id limitation and OpenAI's server-side `tracing` setting); next to the streamed-run notes at `:476` and `:561`.
  - `docs/docs/integrations/hooks.md`: per-turn state in the volatile cache is reset by the hook at `MessageEnd`.
- **Code docstrings:** `core/base.py:610` ("for WebSocket connections"); the same text in `OpenAIModule.__init__` (`framework/openai/openai.py:920`).
- **Dev skills:**
  - `.agents/skills/ak-dev-architecture/SKILL.md`: `:638` (the session is stored at a normal call end; the call span), `:641` (the store at close).
  - `.agents/skills/ak-dev-new-tracing-provider/SKILL.md:22`: the two optional realtime methods and `TracedRealtimeRunner`, and the Langfuse export-filter rule.
  - `.agents/skills/ak-dev-testing-conventions/SKILL.md` (table at `:74-75`): rows for the three new test files.
- **User skills:** `ak-py/src/agentkernel/skills/ak-add-capabilities/SKILL.md:837` (realtime calls): add that the session is stored when a call ends and a call is traced. Checked: no other bundled skill states realtime session or tracing behaviour.
- **Confirm** with the `ak-dev-sync-docs-from-branch` and `ak-dev-sync-skills-from-branch` flows before merge.
