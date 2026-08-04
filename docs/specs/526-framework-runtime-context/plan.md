# #526: Per-run framework context/state through the Session — Implementation Plan

Ordering only — every component, rule, and test named here is detailed in [`spec.md`](spec.md).
Each iteration leaves the branch working and testable on its own.

## Iteration 1: Session key and accessors

- **Goal:** a caller can set, read, and clear a `framework_context` dict on a `Session`, and it survives serialization. No adapter reads it yet.
- **Files:** `ak-py/src/agentkernel/core/base.py`
- **Steps:**
  1. Add the `FRAMEWORK_CONTEXT` member to `Session.Keys` (spec §1).
  2. Add `get_framework_context` / `set_framework_context` / `clear_framework_context`, including the non-mutating get and the `dict`-only type check (spec §1a rules 1–4).
  3. Confirm `Session.__init__` / `get_all` / `clear` need no change — `clear()` rebuilds `_data` from the two caches, so it already drops the key.
- **Verify:** `cd ak-py && uv run pytest tests/test_framework_context.py -k Session`

## Iteration 2: Base `Runner` plumbing

- **Goal:** the load / merge / write-back / picklability seam exists on `Runner` and is fully tested against a dummy subclass, before any framework depends on it.
- **Files:** `ak-py/src/agentkernel/core/base.py`
- **Steps:**
  1. Add `_load_framework_context` (deep copy, absent ⇒ `None`, non-dict ⇒ `TypeError`) and `_store_framework_context` (shallow merge, no-op when absent) — spec §2 rules 1–3.
  2. Add `_not_picklable` / `_ensure_framework_context_picklable` (fail-fast on `run`) and `_log_framework_context_stream_failure` (log-not-raise on `stream`) — spec §2 rules 4–5 and Error handling.
  3. Add the `ak.core.runner` module logger and the `copy` / `pickle` imports.
- **Verify:** `cd ak-py && uv run pytest tests/test_framework_context.py`

## Iteration 3: Full-fidelity adapters — OpenAI and Pydantic AI

- **Goal:** the two frameworks with a real per-run caller-state slot round-trip the context in both `run()` and `stream()`.
- **Files:** `framework/openai/openai.py`, `framework/pydanticai/pydanticai.py`
- **Steps:**
  1. OpenAI: inject `context=`, write back the same object, place the write-back inside the `try` after the native call (spec §3.1).
  2. Pydantic AI: inject `deps=`, same placement; record the two caveats (`deps` is not validated against `deps_type`; `agent.override(deps=...)` suppresses injection) — spec §3.6.
  3. Mirror both in `stream()`, with the write-back after the loop and guarded per Error handling.
- **Verify:** `cd ak-py && uv run pytest tests/test_openai_runner.py tests/test_pydanticai_runner.py`

## Iteration 4: Partial-fidelity adapters — ADK, LangGraph, smolagents

- **Goal:** the three frameworks whose native state is lossy round-trip what they can, with the loss documented rather than hidden.
- **Files:** `framework/adk/adk.py`, `framework/langgraph/langgraph.py`, `framework/smolagents/smolagents.py`
- **Steps:**
  1. ADK: `_setup_session_context` takes `injected` and returns `adk_session`; add `GoogleADKSession.get_state()` with the `ak_tool_context` + `app:`/`user:`/`temp:` stripping; wire `run`/`stream` (spec §3.3). Drain `get_response`'s event stream instead of breaking on the first final response — the early `break` cancels ADK's root-agent task and loses later state deltas (spec Behavioural change 3b).
  2. LangGraph: spread `incoming` into the input state, write `messages` last, write back only declared channels; `stream()` reads state back via `aget_state` (spec §3.4).
  3. Smolagents: inject `additional_args=` only when the key is present, write back `agent.state` filtered to seeded keys (spec §3.2).
- **Verify:** `cd ak-py && uv run pytest tests/test_adk_runner.py tests/test_langgraph_runner.py tests/test_smolagents_runner.py tests/test_tool_adk.py`

## Iteration 5: CrewAI warn-and-skip, and the traced-runner bypass

- **Goal:** no framework silently drops the context, and no traced runner silently bypasses the feature.
- **Files:** `framework/crewai/crewai.py`, `trace/langfuse/langgraph.py`
- **Steps:**
  1. CrewAI: one warning per runner instance when a non-empty context is set; no injection, no write-back (spec §3.5).
  2. `LangFuseLangGraph`: add the `_prepare_session_and_messages` override that wires the Langfuse callback handler into the base config, shrink `run` to a span wrapper around `super().run(...)`, and delete the re-implemented `ainvoke` body plus its now-unused imports (spec §3.7). Confirm the other traced runners already delegate to `super()` and need no change.
- **Verify:** `cd ak-py && uv run pytest tests/test_crewai_runner.py tests/test_trace_langfuse_langgraph.py`

## Iteration 6: Drive-by fixes in the files already open

- **Goal:** the duplication and latent bugs sitting on the lines this change edits are fixed with the same tests, not left for later.
- **Files:** `core/base.py`, `framework/{openai,crewai,adk}/*.py`, `cli/cli.py`
- **Steps:**
  1. Extract `Agent._append_tools` and point the OpenAI / CrewAI / ADK `attach_tool` implementations at it (spec Behavioural change 9).
  2. Initialize `prompt = ""` before the `try` in the OpenAI, LangGraph and ADK `run()` bodies — the `except` handler already referenced it (spec Behavioural change 11).
  3. `CLI._ainput`: read input on a daemon thread so background tasks keep running between turns — required by the `adk_context` example's LiteLLM logging worker (spec Behavioural change 10).
- **Verify:** `cd ak-py && uv run pytest tests/test_cli.py tests/test_tool_openai.py tests/test_tool_crewai.py tests/test_tool_adk.py`

## Iteration 7: Examples

- **Goal:** each supported framework has a runnable demo of the round trip, exercised by CI.
- **Files:** `examples/cli/{openai,langgraph,adk,pydanticai}_context/`, `.github/test-config.yaml`
- **Steps:**
  1. One grocery-cart demo per framework: hooks seed and read through the `Session` accessors, tools use the framework-native handle (`RunContextWrapper.context`, a declared state channel, `ToolContext.state`, `RunContext.deps`).
  2. `demo_test.py` per example asserting cross-turn cart persistence off a deterministic post-hook line, not fuzzy LLM text.
  3. Register all four under `.github/test-config.yaml` for end-to-end CI runs.
- **Verify:** each example's `./build.sh && uv run pytest demo_test.py`

## Iteration 8: Tests

From spec.md's Testing section:

- **New:** `tests/test_framework_context.py` (base plumbing + `Session` accessors), `tests/test_trace_langfuse_langgraph.py` (the §3.7 bypass regression), `tests/test_cli.py` (`_ainput` and the command loop).
- **Changed patch targets:** `tests/test_adk_runner.py`'s `_run_with_response` moves from a 3-tuple to a 4-tuple `("user", runner, ctx, adk_session)` with an `AsyncMock` `get_state`; `tests/test_langgraph_runner.py`'s `_mock_agent` gains `aget_state`; `tests/test_smolagents_runner.py`'s existing `to_thread` assertion becomes the explicit no-context case.
- **Per adapter:** injection, write-back, error-leaves-context-intact, and — for every streaming adapter — normal drain, disconnect-skips-write-back, absent-key, and guarded-failure-is-logged.
- **Verify:** `cd ak-py && uv run pytest`

## Iteration 9: Sync docs and skills

- **Docs:** `core-concepts/session.md` (the feature, the accessors, the hooks-vs-tools scope and its lost-update warning), `core-concepts/runner.md` (fidelity table), `integrations/hooks.md` (ordering guarantee), `frameworks/{openai,pydantic-ai,smolagents,google-adk,langgraph,crewai}.md` (per-framework fidelity + native handle), `frameworks/multi-framework.md` (cross-framework divergence), `examples/overview.md` (the four new examples).
- **Skills:** `.agents/skills/ak-dev-architecture/SKILL.md` (Session key list, Runner responsibilities) and `.agents/skills/ak-dev-new-framework-integration/SKILL.md` (a new adapter must call the load/write-back helpers, name its native slot, and declare its fidelity).
- **No update needed:** deployment READMEs and config docs — there is no config surface (spec Config changes).
- **Verify:** run the `ak-dev-sync-docs-from-branch` and `ak-dev-sync-skills-from-branch` flows before merge.
