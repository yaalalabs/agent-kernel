# #758: Per-run computed run options: a callable form of Module.run_options: Implementation Plan

Orders the build of `spec.md`. The resolution step is inert for an agent without a factory, so each
iteration leaves the branch working and the whole suite green. Work happens on
`feature/dynamic-run-options` off `develop` (which already contains #754); the PR title is
`feat: per-run computed run options through Module.run_options (#758)`. The spec documents are
committed before any code so reviewers read them first.

## Iteration 1: Core seam

- **Goal:** `RunOptionsFactory`, `Agent.run_options_factory`, `Agent.resolve_run_options` and the
  positional-only `factory` parameter on `Module.run_options` exist and are tested; no adapter calls
  the resolver yet.
- **Files:** `ak-py/src/agentkernel/core/base.py`, `ak-py/src/agentkernel/core/module.py`,
  `ak-py/src/agentkernel/core/__init__.py`, `ak-py/tests/test_base.py`, `ak-py/tests/test_module.py`.
- **Steps:**
  1. Write the `test_base.py` and `test_module.py` assertions from spec § Testing first (no-factory
     copy, sync and async merge, argument identity, non-mapping `TypeError`, reserved key
     `ValueError`, propagation, static dict untouched; storing, replacing, non-callable, no-op,
     chaining).
  2. Add the alias and the two `Agent` members (spec § `Agent`), export the alias
     (`core/__init__.py:14`), and change the `Module.run_options` signature (spec § `Module`).
- **Verify:** `cd ak-py && uv run pytest tests/test_base.py tests/test_module.py`, then the full
  `uv run pytest` to confirm nothing else moved.

## Iteration 2: Test doubles

- **Goal:** every mock agent the runner tests hand to a runner exposes `run_options` and an
  awaitable `resolve_run_options`, so the adapters can start awaiting it without a red suite.
- **Files:** `ak-py/tests/test_openai_runner.py`, `test_langgraph_runner.py`, `test_adk_runner.py`,
  `test_pydanticai_runner.py`, `test_crewai_runner.py`, `test_smolagents_runner.py`,
  `test_trace_langfuse_langgraph.py`, `test_tool_adk.py`.
- **Steps:**
  1. Add the two attributes to the eight existing helpers (`_mock_agent` in five files,
     `_mock_stream_agent`, `_capturing_stream_agent`, `_mock_stream_events_agent`), with
     `resolve_run_options = AsyncMock(side_effect=lambda session, requests: dict(agent.run_options))`
     so later `run_options = {...}` assignments are honoured (spec § Consumer changes).
  2. Introduce `_mock_agent()` in `test_openai_runner.py`, `test_smolagents_runner.py` and
     `test_tool_adk.py` and replace the 43 inline `MagicMock()` agents there with it; give
     `test_pydanticai_runner.py` a `_bare_agent()` helper shared by its three helpers and five inline
     mocks; route the one inline ADK mock through `_mock_agent()`.
  3. Add `"resolve_run_options"` to the CrewAI spec-restricted mock's spec list.
- **Verify:** `uv run pytest tests/test_*_runner.py tests/test_trace_langfuse_langgraph.py` is green
  with the adapters still untouched (the attributes are unused until Iteration 3), and the CrewAI
  file through the `uv run --with "crewai>=1.15.0"` overlay.

## Iteration 3: OpenAI and smolagents adapters

- **Goal:** the two adapters with a single native call site resolve once per method.
- **Files:** `ak-py/src/agentkernel/framework/openai/openai.py`,
  `ak-py/src/agentkernel/framework/smolagents/smolagents.py`, their two test files.
- **Steps:**
  1. Tests first: a factory value wins over a static key at the native call; `resolve_run_options`
     awaited exactly once with `(session, requests)` per `run` and, for OpenAI, per `stream`.
  2. Insert the resolution line after the early returns and switch the helper calls to `options`
     (spec § Resolution in the adapters).
- **Verify:** `uv run pytest tests/test_openai_runner.py tests/test_smolagents_runner.py`.

## Iteration 4: LangGraph and Pydantic AI adapters

- **Goal:** the two adapters with a per-mode helper resolve once and pass the mapping through it.
- **Files:** `framework/langgraph/langgraph.py`, `framework/pydanticai/pydanticai.py`, their test
  files, `tests/test_trace_langfuse_langgraph.py`.
- **Steps:**
  1. Tests first: factory `config.recursion_limit` reaches `ainvoke` merged with the AK config;
     factory `usage_limits` reaches `agent.run`; the stream filter still drops
     `event_stream_handler` from a factory result; once-per-method awaits; the trace pass-through.
  2. `_stream_run_options(options)` takes the mapping; both adapters' `run` / `stream` resolve and
     read `options` (spec § Resolution in the adapters).
- **Verify:** `uv run pytest tests/test_langgraph_runner.py tests/test_pydanticai_runner.py tests/test_trace_langfuse_langgraph.py`.

## Iteration 5: Google ADK and CrewAI adapters

- **Goal:** the two adapters that construct their native runner per run resolve before that
  construction.
- **Files:** `framework/adk/adk.py`, `framework/crewai/crewai.py`, their test files.
- **Steps:**
  1. Tests first: `_setup_session_context` receives the resolved options and a factory-supplied
     `plugins` reaches the `Runner` constructor; a factory `run_config` reaches `run_async` in run
     mode and is SSE-copied in stream mode; a factory `max_rpm` reaches `Crew`; once-per-method awaits.
  2. `_split_run_options(options)` takes the mapping; `_setup_session_context` gains the trailing
     `options` parameter; `run` / `stream` resolve first and pass it (spec § Resolution in the
     adapters). CrewAI reads `options` at its `Crew(...)` call.
- **Verify:** `uv run pytest tests/test_adk_runner.py tests/test_tool_adk.py` and the CrewAI files
  through the overlay.

## Iteration 6: Whole-suite tests and lint

- **Goal:** the complete `ak-py` suite is green with all six adapters converted, and formatting passes.
- **Files:** none new; fixes only where the suite reveals them.
- **Steps:**
  1. `cd ak-py && uv run pytest` (the pre-existing `call_args` assertions are the regression guard
     for Behavioural change 3).
  2. `make lint-check`; `make lint` if it fails.
  3. Re-read spec § Behavioural changes and confirm each of the six items is implemented; none may
     be silently missing.
- **Verify:** both commands exit 0.

## Iteration 7: Example

- **Goal:** a new demo shows a factory beside static keywords, and its test proves the factory ran.
- **Files:** `examples/cli/openai-dynamic-run-options/` (`README.md`, `build.sh`, `demo.py`,
  `demo_test.py`, `pyproject.toml`, `uv.lock`); `.github/test-config.yaml`;
  `docs/docs/examples/overview.md`; `docs/docs/frameworks/openai.md`.
- **Steps:**
  1. Scaffold from `examples/cli/openai-run-options`: copy `build.sh`, adapt the `pyproject.toml`
     name and description, run `uv lock` (against the index, not the local dist, so the committed
     lock matches its siblings).
  2. Write `demo.py` per spec § Documentation changes: the weather agent, `ProgressHooks`,
     `options_for` (bumps `factory_runs`, `max_turns=10` plus per-session `trace_metadata` for a
     `guest` session, metadata only otherwise, records the effective `max_turns` in the volatile
     cache), the `run_options(weather_agent, options_for, max_turns=MAX_TURNS, hooks=ProgressHooks())`
     declaration, and a post-hook reading `max_turns` and `factory_runs` from the cache.
  3. Write `demo_test.py` (two ordered turns; `factory_runs >= 1`, `max_turns == 25`,
     `tool_calls >= 1`) and `README.md` (the factory contract, merge order, shared-instance rule,
     the guest switch, the run block).
  4. Add the `type: cli` entry to `.github/test-config.yaml` beside `openai-run-options`, a bullet
     in the run-options block of `docs/docs/examples/overview.md`, and a link in the "Example"
     section of `docs/docs/frameworks/openai.md`.
- **Verify:** `cd examples/cli/openai-dynamic-run-options && ./build.sh local && OPENAI_API_KEY=... uv run pytest -s`
  where a key is available, else the import check (`uv run --no-sync python -c "import demo"`),
  `uv run --no-sync pytest --collect-only -q`, and `make lint-check-all`; the live run happens in
  the e2e job. Confirm the lock's `agentkernel` source is the index, not `../../../ak-py/dist`.

## Iteration 8: Sync docs and skills

- **Goal:** every surface that describes `run_options` also describes the factory form.
- **Files and lines** (from spec § Documentation changes):
  - `docs/docs/core-concepts/runner.md:295`: the "Computed per run" paragraph before "Progress: two
    paths", including the ADK `ToolContext` caveat.
  - `docs/docs/core-concepts/module.md:131-155` and `docs/docs/core-concepts/agent.md:263`.
  - `docs/docs/frameworks/google-adk.md` ("Native run options"): one sentence on the `ToolContext`
    caveat for factories.
  - `.agents/skills/ak-dev-architecture/SKILL.md:92` (Agent) and `:115` (Module);
    `.agents/skills/ak-dev-new-framework-integration/SKILL.md:122` (step 3 bullet) and `:426`
    (checklist); `.agents/skills/ak-dev-testing-conventions/SKILL.md` (the `test_base.py` and
    `test_module.py` rows).
  - `ak-py/src/agentkernel/skills/ak-add-capabilities/SKILL.md:637` and `ak-build/SKILL.md:396`,
    plus the `cap-run-options-factory` eval entry.
  - `docs/docs/examples/overview.md`, `docs/docs/frameworks/openai.md` and
    `.github/test-config.yaml` are updated in Iteration 7 with the new example; check them here.
  - **No update needed** (verified by grep for `run_options` outside the files above): the other
    five framework pages, `hooks.md`, the intro What's New tip, the root and package READMEs, the
    deployment READMEs, and the docs-site React pages.
- **Steps:**
  1. Run `ak-dev-sync-docs-from-branch` and `ak-dev-sync-skills-from-branch` against the branch and
     hand-check the list above.
  2. Confirm no em or en dashes were introduced
     (`grep -rnP "\x{2014}|\x{2013}"` over the added lines must print nothing) and that the eval JSON
     parses.
- **Verify:** `cd docs && NODE_ENV=production NODE_OPTIONS=--max-old-space-size=6144 npm run build`;
  the two sync skills report no remaining drift.

## Follow-ups outside this change (recorded, not planned)

- A strip of `RESERVED_RUN_OPTIONS` inside `Runner._native_kwargs`, which would make a bypassed
  reserved key harmless on every adapter at once (raised in the #756 review and left open there).
