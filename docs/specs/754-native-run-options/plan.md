# #754: Per-agent native run options for framework adapters: Implementation Plan

Orders the build of `spec.md`. Every iteration leaves `develop` plus the branch in a working, testable
state; the `run_options` seam is inert until an application declares options, so partially converted
adapters never change behaviour for existing agents. Work on a feature branch off `develop`; the PR
title is `feat: per-agent native run options for framework adapters (#754)`. The design and survey
are committed in `6831c02f` and the spec in `4c9cec16` on `feature/framework_native_run_options`;
the Examples amendments to both and this plan are committed before any code so reviewers read the
spec set first.

## Iteration 1: Core seam

- **Goal:** `Agent.run_options`, `Agent.RESERVED_RUN_OPTIONS`, `Agent.validate_run_options`,
  `Module.run_options`, `Module._native_agent_name`, `Runner._native_kwargs` exist and are tested; no
  adapter reads them yet.
- **Files:** `ak-py/src/agentkernel/core/base.py`, `ak-py/src/agentkernel/core/module.py`,
  `ak-py/tests/test_base.py`, `ak-py/tests/test_module.py`.
- **Steps:**
  1. Write the `test_base.py` and `test_module.py` assertions from spec § Testing first (default
     `{}`, reservation error text, merge last-wins, unknown agent, `_native_agent_name` override,
     `_native_kwargs` copy semantics, `SimpleModule` still constructs).
  2. Add the `Agent` members (spec § `Agent`), the `Module` members (spec § `Module`), and the static
     `Runner._native_kwargs` (spec § `Runner`).
- **Verify:** `cd ak-py && uv run pytest tests/test_base.py tests/test_module.py`; then the full
  `uv run pytest` to confirm nothing else moved.

## Iteration 2: OpenAI adapter

- **Goal:** `OpenAIRunner.run` / `stream` build their SDK call through `_native_kwargs`; the user's
  `hooks` / `run_config` / `max_turns` reach the SDK; a native hook sees the AK session.
- **Files:** `ak-py/src/agentkernel/framework/openai/openai.py`, `ak-py/tests/test_openai_runner.py`.
- **Steps:**
  1. Add the `run_options` assertions from spec § Testing (options forwarded on `run` and
     `run_streamed`, AK `context` wins, declared dict unmutated) and the two `Session.current()` /
     `Agent.current()`-inside-`RunHooks` tests (run and stream).
  2. Declare `OpenAIAgent.RESERVED_RUN_OPTIONS`; rewrite the two call sites (spec § OpenAI adapter).
- **Verify:** `uv run pytest tests/test_openai_runner.py tests/test_framework_context.py`.

## Iteration 3: LangGraph adapter

- **Goal:** `config` deep-merges (AK `thread_id`, concatenated `callbacks`), the nested `thread_id`
  is rejected at declaration, `version="v2"` stays AK-owned, and the Langfuse handler survives a
  caller's callbacks.
- **Files:** `ak-py/src/agentkernel/framework/langgraph/langgraph.py`,
  `ak-py/tests/test_langgraph_runner.py`, `ak-py/tests/test_trace_langfuse_langgraph.py`.
- **Steps:**
  1. Tests: `_merge_run_config` unit cases (dict merge, list concat, scalar AK-wins), the forwarded
     `interrupt_before`, the nested `thread_id` rejection, and the Langfuse composition case.
  2. `LangGraphAgent.RESERVED_RUN_OPTIONS` + `validate_run_options` override; `_merge_run_config`;
     rewrite `ainvoke` / `astream_events` call sites (spec § LangGraph adapter).
- **Verify:** `uv run pytest tests/test_langgraph_runner.py tests/test_trace_langfuse_langgraph.py`.

## Iteration 4: Google ADK adapter

- **Goal:** constructor options reach the per-run `Runner(...)`, `run_config` reaches `run_async`,
  stream mode forces SSE on a copy with one warning, `get_response` keeps its four-argument callers.
- **Files:** `ak-py/src/agentkernel/framework/adk/adk.py`, `ak-py/tests/test_adk_runner.py`.
- **Steps:**
  1. Tests: split routing, run-mode `RunConfig` untouched, stream-mode SSE copy + caller object
     unchanged + single warning across two streams, `_split_run_options` on the constant.
  2. `GoogleADKAgent.RESERVED_RUN_OPTIONS`; `RUNNER_CONSTRUCTOR_OPTIONS`, `_split_run_options`,
     `_stream_run_config`, the `_streaming_mode_warned` flag; `_setup_session_context`,
     `get_response`, `run`, `stream` rewrites (spec § Google ADK adapter).
- **Verify:** `uv run pytest tests/test_adk_runner.py tests/test_tool_adk.py`.

## Iteration 5: Pydantic AI adapter

- **Goal:** options reach `agent.run`; stream drops `event_stream_handler` with one warning and
  leaves the declared dict intact.
- **Files:** `ak-py/src/agentkernel/framework/pydanticai/pydanticai.py`,
  `ak-py/tests/test_pydanticai_runner.py`.
- **Steps:**
  1. Tests per spec § Testing (run forwards both, stream drops the handler, one warning, dict intact).
  2. `PydanticAIAgent.RESERVED_RUN_OPTIONS`; `_event_stream_handler_warned`; `_stream_run_options`;
     rewrite the two call sites (spec § Pydantic AI adapter).
- **Verify:** `uv run pytest tests/test_pydanticai_runner.py`.

## Iteration 6: CrewAI and smolagents adapters

- **Goal:** the two adapters with per-run native constructors / kwargs dicts read options, and the two
  modules whose name rule is not `agent.name` override `_native_agent_name`.
- **Files:** `ak-py/src/agentkernel/framework/crewai/crewai.py`,
  `ak-py/src/agentkernel/framework/smolagents/smolagents.py`, `ak-py/tests/test_crewai_runner.py`,
  `ak-py/tests/test_smolagents_runner.py`.
- **Steps:**
  1. Add `"run_options"` to the spec-restricted mock at `test_crewai_runner.py:34` and set it to `{}`
     (spec § Consumer changes); add the `Crew` kwargs assertions (`step_callback`, `verbose`
     overridable, `{}` reproduces today's kwargs) and the smolagents `to_thread` kwargs assertions
     (`max_steps`, `reset` overwritten).
  2. `CrewAIAgent.RESERVED_RUN_OPTIONS`, `CrewAIModule._native_agent_name`, the `Crew(...)` rewrite;
     `SmolagentsAgent.RESERVED_RUN_OPTIONS`, `SmolagentsModule._native_agent_name`, the `run_kwargs`
     rewrite (spec § CrewAI adapter, § smolagents adapter).
- **Verify:** `uv run pytest tests/test_crewai_runner.py tests/test_smolagents_runner.py`.

## Iteration 7: Whole-suite tests and lint

- **Goal:** the complete `ak-py` suite is green with the six adapters converted, and formatting passes.
- **Files:** none new; fixes only where the suite reveals them.
- **Steps:**
  1. `cd ak-py && uv run pytest` (every `call_args` assertion in the runner tests is the regression
     guard for Behavioural change 3).
  2. `make lint-check`; run `make lint` if it fails.
  3. Re-read spec § Behavioural changes and confirm each numbered item is either implemented or
     deliberately deferred; none may be silently missing.
- **Verify:** both commands exit 0.

## Iteration 8: Per-framework examples

- **Goal:** six runnable CLI demos declaring that framework's turn-limit and progress-hook options,
  each with a deterministic `Run stats:` assertion (spec § Examples).
- **Files:** `examples/cli/openai_run_options/`, `examples/cli/langgraph_run_options/`,
  `examples/cli/adk_run_options/`, `examples/cli/pydanticai_run_options/`,
  `examples/cli/crewai_run_options/`, `examples/cli/smolagents_run_options/` (each: `README.md`,
  `build.sh`, `demo.py`, `demo_test.py`, `pyproject.toml`, `uv.lock`); `.github/test-config.yaml`;
  `docs/docs/examples/overview.md`.
- **Steps:**
  1. Scaffold each directory from its `_context` sibling (or `examples/cli/crewai` /
     `examples/cli/smolagents` where no `_context` sibling exists): copy `build.sh`, adapt
     `pyproject.toml` name and extra, run `uv lock`.
  2. Write `demo.py` per the spec's per-framework table: the progress hook writing counters into
     `Session.current().get_volatile_cache()`, the declared `run_options(...)` call, and
     `AppendRunStatsPostHook`.
  3. Write `demo_test.py` (two ordered turns; assert the stats line, exact `limit=`, counters >= 1)
     and `README.md` (declaration, destination, reserved keys, the two progress paths, run block).
  4. Add the six `type: cli` entries to `.github/test-config.yaml` under `e2e.tests`, beside the
     `_context` entries. Note for the requester: `examples/cli/smolagents` is absent from that
     matrix today; the new smolagents example is added, and can be dropped for parity if preferred.
  5. Add a "Per-agent native run options demos" block to the CLI section of
     `docs/docs/examples/overview.md` beside the `_context` block (`:47-52`).
- **Verify:** for each directory, `./build.sh local && uv run pytest -s` with `OPENAI_API_KEY` set;
  `make lint-check-all` (examples are formatted at line length 120).

## Iteration 9: Sync docs and skills

- **Goal:** every documentation and skill surface names the new API and no surface describes the
  old fixed-kwargs behaviour as the only path.
- **Files and lines** (from spec § Documentation changes):
  - `docs/docs/core-concepts/runner.md:216-243`: new `### Per-agent native run options` section with
    the per-framework table and the concurrency note on shared hook instances.
  - `docs/docs/core-concepts/module.md:118`: `run_options` under "Module Configuration".
  - `docs/docs/core-concepts/agent.md:229`: `#### Run options` under "Agent Properties".
  - `docs/docs/integrations/hooks.md:396`: pointer paragraph and the two-path progress table.
  - `docs/docs/frameworks/openai.md:113`, `langgraph.md:134`, `google-adk.md:116`,
    `pydantic-ai.md:179`, `crewai.md:121`, `smolagents.md:121`: `## Native run options` after
    "Per-run context/state", plus the example link in each page's "Example" section (pattern
    `openai.md:132`).
  - `docs/docs/advanced/traceability.md:477-500`: fix the custom-runner signature; redirect
    keyword-argument needs to run options.
  - `.agents/skills/ak-dev-architecture/SKILL.md:85` (Agent), `:96` and `:104` (Runner),
    `:106` (Module).
  - `.agents/skills/ak-dev-new-framework-integration/SKILL.md:256` (step 4), `:305` (step 6), and
    the checklist at `:421`; step 3 gains the `_native_kwargs` rule.
  - `.agents/skills/ak-dev-testing-conventions/SKILL.md`: the `test_base.py` / `test_module.py` rows
    of the test-file table mention run options.
  - **No update needed** (verified by grep for `runner=`, `pre_hook`, `framework_context` in the
    remaining surfaces): `ak-py/README.md`, the root `README.md`, `docs/docs/core-concepts/session.md`
    (run options are not session state), the deployment READMEs, and the docs-site React pages
    (`docs/src/pages/*.tsx` enumerate frameworks, not module APIs).
- **Steps:**
  1. Run `ak-dev-sync-docs-from-branch` and `ak-dev-sync-skills-from-branch` against the branch, then
     hand-check the list above against their output.
  2. Confirm no em or en dashes were introduced in docs or skills
     (`grep -rnP "\x{2014}|\x{2013}" docs/docs .agents/skills` must print nothing).
- **Verify:** `cd docs && NODE_ENV=production npm run build` (the docs build needs the production
  flag and the enlarged heap noted in the repo's docs-site build guidance); the two sync skills
  report no remaining drift.

## Follow-ups outside this change (recorded, not planned)

- Rewriting the six `pre_hook` / `post_hook` implementations to use `Module._native_agent_name`
  (spec § `Module`, item 4): a behaviour-preserving cleanup.
- A callable form of `run_options` for per-session variation (design, Non-goals).
- Whether `examples/cli/smolagents` itself should join the e2e matrix (Iteration 8, step 4).
