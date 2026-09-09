# #545: Add Pydantic Logfire as a tracing provider — Implementation Plan

Builds the design (`design.md`) per the spec (`spec.md`). Each iteration leaves the branch working
and testable.

## Iteration 1: Provider package + factory registration

- **Goal:** `trace.type: logfire` resolves to a working `Logfire` provider for all five frameworks.
- **Files:**
  - `ak-py/src/agentkernel/trace/logfire/__init__.py` (empty)
  - `ak-py/src/agentkernel/trace/logfire/logfire.py`
  - `ak-py/src/agentkernel/trace/logfire/{openai,langgraph,crewai,adk,smolagents}.py`
  - `ak-py/src/agentkernel/trace/trace.py` (edit)
  - `ak-py/pyproject.toml` (edit — add `logfire` extra)
- **Steps:**
  1. `Logfire(BaseTrace)` with once-guarded `init()` + five lazy runner methods (spec.md → `Logfire`).
  2. Five traced runners on the shared shape; per-framework `__init__` instrumentation from the
     spec.md coverage table.
  3. Add `logfire` to `_BUILTIN_TRACERS` and a `require_extra`-wrapped branch in `_build()`
     (spec.md → Consumer changes).
  4. Add the `logfire = ["logfire>=3.0"]` extra (spec.md → Optional dependency).
- **Verify:** `cd ak-py && uv run pytest tests/test_trace.py` (existing suite still passes; import of
  `trace/trace.py` unbroken).

## Iteration 2: Configuration description

- **Goal:** generated config docs advertise `logfire`.
- **Files:** `ak-py/src/agentkernel/core/config.py` (edit `_TraceConfig.type` description).
- **Steps:** update the description string only (spec.md → Config changes).
- **Verify:** `cd ak-py && uv run pytest tests/test_config.py`.

## Iteration 3: Example

- **Goal:** a runnable CLI example that traces to Logfire.
- **Files:** `examples/cli/logfire/{demo.py,config.yaml,pyproject.toml,build.sh,README.md,demo_test.py}`.
- **Steps:** copy the `examples/cli/openai/` structure; add `config.yaml` enabling `trace.type: logfire`;
  depend on `agentkernel[cli,openai,logfire]`; README documents `LOGFIRE_TOKEN` + local mode
  (spec.md → Example).
- **Verify:** `cd examples/cli/logfire && ./build.sh local` (optional; needs SDKs + keys — document,
  don't gate CI on it).

## Iteration 4: Tests

- **Goal:** factory resolution, once-guard, span wrapping, error recording, and instrumentation covered.
- **Files:**
  - `ak-py/tests/test_trace.py` (add the `logfire` missing-extra test)
  - `ak-py/tests/test_trace_logfire.py` (new — `fake_logfire` fixture + the six tests in spec.md →
    Testing)
- **Steps:** implement per spec.md → Testing (mock the `logfire` module; patch base `run` and the
  crewai/adk OpenInference instrumentors).
- **Verify:** `cd ak-py && uv run pytest tests/test_trace.py tests/test_trace_logfire.py`, then the full
  `uv run pytest`; `make lint-check-all`.

## Iteration 5: Docs and skills sync

- **Files / surfaces:**
  - `docs/docs/advanced/traceability.md` — add a Logfire section (install, config, `LOGFIRE_TOKEN`,
    what gets traced, coverage table, troubleshooting) and list Logfire under "Supported Platforms".
  - `.agents/skills/ak-dev-new-tracing-provider/SKILL.md` (the only in-repo copy) — the "Adding a New
    Tracing Provider" guide listed `_BUILTIN_TRACERS = ["langfuse", "openllmetry"]`; updated to include
    `logfire` (factory branch + config description) so the example matches the shipped list. Verified no
    other skill hardcodes the tracer list.
  - Bundled user skills (`ak-add-capabilities`, `ak-init`, `ak-build`) and the other doc surfaces that
    listed only two providers (root `README.md`, `ak-py/README.md`, `configuration.md`, `overview.md`,
    `agent-skills.md`) — updated to include Logfire.
  - Confirm the `ak-dev-sync-docs-from-branch` / `ak-dev-sync-skills-from-branch` flows before merge.
- **Verify:** docs build; grep `_BUILTIN_TRACERS`/`openllmetry` across `docs/` and skills to confirm no
  stale two-provider lists remain (excluding versioned_docs snapshots, which are frozen).
