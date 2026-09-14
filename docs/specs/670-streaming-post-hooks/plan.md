# #670: Streaming post-hooks never see tool-call events — Implementation Plan

Iterations 1–5 are PR 1, iteration 6 is PR 2, per `design.md`'s Delivery section. Section references
are to `spec.md`.

**One ordering constraint shapes the whole plan.** Deleting `PostHook.on_stream_chunk` and switching
`Runtime.stream` to `on_stream_event` cannot be separated from rewriting the four tests that exercise
the old callback — no ordering of those three leaves the branch green in between, because the tests
fail the moment the Runtime stops calling the method they override. Iteration 3 therefore carries all
three together, and iteration 4 adds the genuinely new coverage. Every other iteration is additive.

## Iteration 1: The hook contract

- **Goal:** `StreamHalt` and `PostHook.on_stream_event` exist and are importable; nothing calls them
  yet, so behaviour is unchanged.
- **Files:** `ak-py/src/agentkernel/core/hooks.py`, `ak-py/src/agentkernel/core/__init__.py`
- **Steps:**
  1. Add `StreamHalt` (spec § *`core/hooks.py`*), carrying `reason`.
  2. Add `PostHook.on_stream_event` with the pass-through default and the docstring stating the
     list-ends-the-chain rule. Leave `on_stream_chunk` in place for now.
  3. Extend `core/__init__.py:47` to `from .hooks import PreHook, PostHook, StreamHalt`.
- **Verify:** `cd ak-py && uv run pytest` — fully green, since nothing yet calls the new method.
  `python -c "from agentkernel import StreamHalt"` resolves.

## Iteration 2: The boundary tracker

- **Goal:** `StreamBoundaryTracker` exists and is correct in isolation, still unused.
- **Files:** `ak-py/src/agentkernel/core/runtime.py`,
  `ak-py/tests/test_stream_boundaries.py` (new)
- **Steps:**
  1. Write `StreamBoundaryTracker` with `observe` / `drain`, declared above `Runtime`
     (spec § *`core/runtime.py` — `StreamBoundaryTracker`*, rules 1–7).
  2. Add the direct unit test. `spec.md` calls this optional because iterations 4's halt tests cover
     the class end-to-end — but without it this iteration has nothing to verify beyond "the suite is
     still green", which is not a check on code that is not yet wired in. Cover: open/close pairing per
     kind, innermost-first drain order, `drain` clearing, a close for an id never opened being a no-op,
     and a second open for the same id overwriting.
- **Verify:** `cd ak-py && uv run pytest tests/test_stream_boundaries.py` then the full suite.

## Iteration 3: Switch the Runtime, delete the old callback

- **Goal:** every event reaches the hook chain; `on_stream_chunk` is gone; the existing streaming
  tests pass against the new contract.
- **Files:** `ak-py/src/agentkernel/core/runtime.py`, `ak-py/src/agentkernel/core/hooks.py`,
  `ak-py/tests/test_runtime_stream_events.py`
- **Steps:**
  1. Change the imports at `core/runtime.py:16` (spec § *`core/runtime.py`*, Imports).
  2. Replace `core/runtime.py:268-286` with the new loop, and the docstring paragraph at `:239-245`.
     Rules 1–8 in that spec section are the acceptance criteria.
  3. Delete `PostHook.on_stream_chunk` (`core/hooks.py:73-85`).
  4. Rewrite `RecordingHook` (`tests/test_runtime_stream_events.py:71-86`) and the module docstring
     (`:1-8`) against `on_stream_event`.
  5. Update the four tests that use it, per the table in spec § *Testing*: `:113-123` (`model_copy`
     rewrite by the hook rather than by the Runtime), `:126-138`, `:141-155` (**reversed** — every
     event now reaches the chain; rename accordingly), `:158-173` (the `delta`-projection assertion is
     the part that must survive).
- **Verify:** `cd ak-py && uv run pytest tests/test_runtime_stream_events.py` green, including the two
  tests that must pass untouched (`:176-187`, `:190-201`), then the full suite. The full run is what
  proves spec § *Consumer changes* — that no consumer needed one — via
  `tests/test_agui_handler.py`, `tests/test_agui_mapping.py`, `tests/test_thread_integration.py` and
  `tests/test_pipeline_agent_runner.py`, none of which this change edits.

## Iteration 4: New coverage

- **Goal:** every decision that could regress silently has a test.
- **Files:** `ak-py/tests/test_runtime_stream_events.py`
- **Steps:** add the nine tests listed in spec § *Testing* → *New tests*. The three that guard
  decisions nothing else would catch are #2 (a list ends the chain), #8 (non-`StreamHalt` propagates
  with no error chunk) and #9 (the no-op case is byte-identical to today).
- **Verify:** `cd ak-py && uv run pytest tests/test_runtime_stream_events.py`, then
  `cd ak-py && uv run pytest`, then `make lint-check-all`.

## Iteration 5: Sync docs and skills

- **Goal:** no surface presents the deleted API as current.
- **Files and lines** (from `design.md` § Documentation; every path verified to mention
  `on_stream_chunk`):
  - `docs/docs/integrations/hooks.md` — `:210-234` replaced by the four class-based examples,
    `:236-243` warning retired, plus the list-ends-the-chain rule and the migration note.
  - `docs/docs/integrations/agui.md:179-182` — the matching "payloads are not filtered" note.
  - `docs/docs/core-concepts/runtime.md:56`, `runner.md:139`, `overview.md:181`.
  - `docs/docs/architecture/overview.md:240-266`, `execution-flow.md:174-182` — both contain mermaid
    sequence diagrams naming `PostHook.on_stream_chunk()`.
  - `ak-py/src/agentkernel/skills/ak-add-capabilities/SKILL.md:588-592`.
  - `.agents/skills/ak-dev-architecture/SKILL.md:98`, `:240`, `:1000`.
  - `.agents/skills/ak-dev-new-framework-integration/SKILL.md:197`.
  - `.agents/skills/ak-dev-testing-conventions/SKILL.md:41`, `:188`.
- **Deliberately not updated**, verified rather than assumed:
  - `docs/versioned_docs/version-0.8.0/` — six files mention `on_stream_chunk`
    (`architecture/execution-flow.md`, `architecture/overview.md`, `core-concepts/overview.md`,
    `core-concepts/runner.md`, `core-concepts/runtime.md`, `integrations/hooks.md`). Versioned docs are
    frozen per `AGENTS.md`; 0.8.0 shipped that API and its docs must keep describing it.
  - `docs/specs/523-ag-ui-support/` — `design.md`, `spec.md`, `plan.md` and `research/ag-ui.md`
    describe what #523 decided and shipped. They are a historical record, not live documentation.
  - No README, deployment doc, Helm chart, Terraform module or example other than PR 2's: this change
    adds no config key, no env var and no deployment surface (spec § *Config changes*).
- **Verify:** `grep -rn "on_stream_chunk" docs/docs .agents ak-py/src/agentkernel/skills` returns
  nothing. Then run `ak-dev-sync-docs-from-branch` and `ak-dev-sync-skills-from-branch` to catch any
  surface this list missed.

## Iteration 6: Runnable example (PR 2)

- **Goal:** a working demonstration of the new callback, on its own branch stacked on PR 1.
- **Files:** `examples/api/hooks-streaming/` — `app.py`, `hooks.py`, `app_test.py`, `build.sh`,
  `README.md`, `pyproject.toml`, following `examples/api/hooks/`'s layout.
- **Steps:**
  1. Branch from PR 1's branch and target it, so GitHub retargets to `develop` on merge.
  2. Write the hooks as `PostHook` subclasses only, per spec § *Conventions* — no module-level
     functions or constants. `examples/api/hooks/hooks.py` is the shape to follow.
  3. Cover the three shapes worth demonstrating: redacting a `ToolCallResult` (no buffering),
     hold-and-release with `session.get_volatile_cache()`, and `StreamHalt`.
  4. Set `execution.mode: stream` in the example's own `config.yaml`. It must be a **new** example:
     `examples/api/hooks` runs non-streaming and its `DisclaimerHook`
     (`examples/api/hooks/hooks.py:159`) implements `on_run`, which `stream()` still never calls, so
     switching that example to stream mode would silently disable its own demonstration.
  5. Line length is 120 in examples, not 150 (`ak-dev-code-quality`).
- **Verify:** `cd examples/api/hooks-streaming && ./build.sh && uv run pytest -s`, then
  `make lint-check-all` from the repo root.
