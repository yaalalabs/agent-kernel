# #912: Benchmark harness (`ak-bench` core) — Implementation Plan

Builds [spec.md](spec.md) in eleven iterations. Section names below are `spec.md` sections. Each iteration adds its own
tests and leaves both projects green:

- harness: `cd benchmarks && uv run pytest -q`
- app: `cd benchmarks/app && uv run pytest -q`

Before starting: the `TraceStage` / `TraceLine` parser comes from #911, which is on this branch but not yet on
`develop`. Merge #911 first (or keep this branch on top of it), or Iteration 3 has nothing to import.

No file under `ak-py/` changes in any iteration.

## Iteration 1: Project skeleton and config

- **Goal:** `benchmarks/` installs with uv, `ak-bench --help` runs, and `ak-bench.yaml` loads into `BenchConfig`
  with every rule of `design.md` Configuration.
- **Files:** `benchmarks/pyproject.toml`, `uv.lock`, `README.md` (install + test commands only for now),
  `ak-bench.example.yaml`, `ak_bench/__init__.py`, `errors.py`, `config.py`, `cli.py` (sub-commands parsed, each
  still raising "not implemented"), `tests/conftest.py` (`fast_config`), `tests/test_config.py`
- **Steps:**
  1. Write `pyproject.toml` as in Dependencies and tooling (path source on `../ak-py`, `ak-bench` script, dev group);
     `uv lock`.
  2. Add the error classes (Errors).
  3. Add `BenchConfig` (an AKConfig-style `YamlBaseSettingsModified` with `get()` / `_reset()`) and its sub-models, `FetchersConfig.poll_interval_for` /
     `check_names`, `MockAgentConfig.delays`, `max_cooldown_for` (Configuration).
  4. Add `ak-bench.example.yaml` with every #786 key and its default plus the two new `step_run` keys.
  5. Add `BenchCli` with the global flags and the six sub-commands' arguments, and `main()` (Commands → CLI).
- **Verify:** `uv run ak-bench --help`; `uv run pytest tests/test_config.py -q`

## Iteration 2: Platform base, CSV store, run log, host registry

- **Goal:** a mock host made of one mock fetcher per family loads, validates, and each family stores its rows by key,
  thread-safely.
- **Files:** `ak_bench/platforms/base.py`, `results/keyed_csv.py`, `run/run_log.py`, `run/fetcher_invoker.py`,
  `hosts.py`, `tests/mocks/fetchers.py`, `tests/mocks/host.py`, `tests/test_fetchers_base.py`,
  `tests/test_family_store.py`, `tests/test_is_settled.py`, `tests/test_registries.py` (host part)
- **Steps:**
  1. Add the dataclasses, `RunInfo`, `Deployment` (`from_json` / `to_json`), `Host` (Platform base).
  2. Add `KeyedCsv` with the per-path lock and temp-file write (Platform base → `KeyedCsv`).
  3. Add `InfoFetcher` (`fetch_and_store`, `is_settled`, `has_value`) and the five family bases with their `store()`
     and `is_settled()` (Platform base → family table).
  4. Add `Fetchers` (`all`, `validate`) with the three refusal rules.
  5. Add `RunLog` (Run log) and `FetcherInvoker` (Step runner → `FetcherInvoker`).
  6. Add `HostRegistry` with an empty `_BUILTINS`; `get()` runs `validate()` (Registries).
  7. Add the mock fetchers and `mock_host()` (Testing → Fixtures).
- **Verify:** `uv run pytest tests/test_fetchers_base.py tests/test_family_store.py tests/test_is_settled.py tests/test_registries.py -q`

## Iteration 3: Benchmarked app (mock agent and token auth)

Independent of Iterations 1–2; can be built in parallel.

- **Goal:** `benchmarks/app/` runs the mock agent or the real agent, and accepts only signed tokens.
- **Files:** `benchmarks/app/pyproject.toml`, `uv.lock`, `README.md`, `agent.py`, `config.yaml`, `mock_agent.py`,
  `identity.py`, `app/deploy/README.md`, `app/tests/test_mock_agent.py`,
  `app/tests/test_identity.py`
- **Steps:**
  1. Write `pyproject.toml` like `e2e/app/pyproject.toml` with `agentkernel[api,openai]` from `../../ak-py`;
     `uv lock` (Dependencies and tooling).
  2. Add `MockRunner` / `MockAgent` (Mock agent app).
  3. Add `BenchIdentityProvider` (Client authentication).
  4. Add `mock_delays()` and `agent.py` (mock vs real selection, raise when only one variable is set) and `config.yaml` (Mock agent app →
     `config.yaml`).
  5. Write `app/deploy/README.md` with the deployment-folder script contract, including "no component sets
     `AK_BENCH_AUTH_SECRET`" (Deployment folders).
- **Verify:** `cd benchmarks/app && uv run pytest -q`

## Iteration 4: Load generator and WebSocket complete driver

- **Goal:** N clients connect to a local mock server, send burst or steady load, and every request ends `ok`,
  `error` or `timeout` with the right timestamps.
- **Files:** `ak_bench/load/records.py`, `driver/base.py`, `driver/ws_complete.py`, `driver/factory.py`, `token.py`,
  `schedule.py`, `generator.py`, `tests/mocks/ws_server.py`, `tests/test_schedule.py`, `tests/test_ws_complete_driver.py`,
  `tests/test_load_generator.py`, `tests/test_token_cross_check.py`, `tests/test_registries.py` (driver part)
- **Steps:**
  1. Add `RequestRecord`, `ResponseEvent`, `RequestStatus` (Load generator → Records).
  2. Add `ClientDriver` and `WebSocketCompleteDriver` (frame, receive task, reply matching, `trace_stages`).
  3. Add `DriverFactory` (Registries).
  4. Add `TokenSigner` (Client authentication).
  5. Add `BurstSchedule` / `SteadySchedule` (Schedules).
  6. Add `LoadGenerator` and `LoadResult` (`connect`, `run`, timeout watcher, `all_settled`, `close`).
  7. Add `MockWsServer` (Testing → Fixtures).
- **Verify:** `uv run pytest tests/test_schedule.py tests/test_ws_complete_driver.py tests/test_load_generator.py tests/test_token_cross_check.py tests/test_registries.py -q`

## Iteration 5: State, step lock, deployment folders, results layout

- **Goal:** a mock deployment folder deploys and destroys through its scripts, `state.json` round-trips, and the step
  lock follows the live / stale / other-machine rules.
- **Files:** `ak_bench/run/state.py`, `run/deployment_folder.py`, `results/layout.py`,
  `tests/mocks/deploy/mock-async-complete/{deploy.sh,destroy.sh}`, `tests/test_state_and_lock.py`
- **Steps:**
  1. Add `ResultsLayout` with the step-folder padding (Results layout).
  2. Add `DeploymentFolder` and `ScriptEnv` (Deployment folders).
  3. Add `DeploymentState` (`locate`, `create`, `update` with `flock`, `0600` file) (State).
  4. Add `StepLock` (`acquire`, `release`, `force_unlock`) (State → Lock rules).
  5. Add the mock deployment folder scripts with `MOCK_DEPLOY_EXIT` / `MOCK_DESTROY_EXIT` (Testing → Fixtures).
- **Verify:** `uv run pytest tests/test_state_and_lock.py -q`

## Iteration 6: Step runner and step-end check

- **Goal:** one step runs connect → before → load → cool-down → wait + fetch against the mock host and server, and
  returns a `StepRecord`.
- **Files:** `ak_bench/scaling/step_end.py`, `run/step_runner.py`, `tests/test_step_end.py`,
  `tests/test_step_runner.py`
- **Steps:**
  1. Add `StepEnd` / `StepEndCheck` (`start`, `poll`, settle window, max cool-down first) (Step-end check).
  2. Add `StepRecord` / `StepRunner` with the tracking tasks, the 30 s stop timeout and the missing-responses
     `WARNING` (Step runner).
- **Verify:** `uv run pytest tests/test_step_end.py tests/test_step_runner.py -q`

## Iteration 7: CSVs and derived numbers

- **Goal:** from a `StepRecord` and the raw fetcher files, every step CSV and the `summary.csv` row are written.
- **Files:** `ak_bench/results/percentiles.py`, `per_request.py`, `per_window.py`, `summary.py`, `metadata.py`,
  `scaling/collector.py`, `scaling/derived.py`, `resources/collector.py`, recorded CSV fixtures under `tests/`,
  `tests/test_results.py`
- **Steps:**
  1. Add `percentiles()` (Percentiles).
  2. Add `PerRequestWriter` (Per-request CSV).
  3. Add `WindowGrid`, `PerWindowWriter`, `ScalingCollector`, `ResourceCollector` with the fill rule and the
     declared empty columns (Per-time-window CSV).
  4. Add `ScalingDerivation` (Derived scaling numbers).
  5. Add `SummaryWriter` (`upsert`, `remove`) (Summary CSV).
  6. Add `RunMetadataWriter` / `StepMetadataWriter` (Metadata).
- **Verify:** `uv run pytest tests/test_results.py -q`

## Iteration 8: Graphs

- **Goal:** every phase-1 graph and the cost graph are drawn from CSVs alone, empty data included.
- **Files:** `ak_bench/results/plots.py`, `cost/report.py`, `tests/test_plots.py`
- **Steps:**
  1. Add `StepPlots` and `TestTypePlots` with the #786 drawing rules, `Agg` backend, temp-file write, per-graph error
     logging (Graphs); use `Scratches/25.Benchmarking-Design/graph-examples/plot_examples.py` for layout only.
  2. Add `CostReport`.
- **Verify:** `uv run pytest tests/test_plots.py -q`

## Iteration 9: Commands and the `run` teardown guarantee

- **Goal:** `deploy`, `step`, `plot`, `finish`, `post-run` and `run` work end to end against the mock host, and
  teardown always runs.
- **Files:** `ak_bench/run/commands.py`, `cli.py` (wire each sub-command to its class, `--force-unlock` help text),
  `README.md` (command reference), `tests/test_commands.py`, `tests/test_teardown_guarantee.py`
- **Steps:**
  1. Add `Deploy` (checks 1–6 before any script, cleanup on `ScriptFailed`) (Commands).
  2. Add `Step` and `Step.force_unlock` (lock in `try / finally`, `--replace`, `summary.csv` row written last).
  3. Add `Plot`, `Finish` (deletes `auth_secret` after a good teardown), `PostRun`.
  4. Add `Run` (dry check of every combination, step order, `Finish` in `finally`, second Ctrl-C handling).
  5. Wire the CLI: `BenchError` → exit 1, `KeyboardInterrupt` → exit 130.
  6. Finish `benchmarks/README.md`: commands, `ak-bench.yaml` reference, when to use `--force-unlock`.
- **Verify:** `uv run pytest tests/test_commands.py tests/test_teardown_guarantee.py -q` (the mock host exists only
  inside the tests, so there is no by-hand `ak-bench run` until the AWS issues add a real host)

## Iteration 10: Tests and CI

- **Goal:** the full suites pass and the harness tests run on every PR.
- **Files:** `.github/workflows/test-reusable.yaml`
- **Steps:**
  1. Add the "Test benchmark harness" step after "Test ak-py" in the `unit-tests` job (Consumer changes).
  2. Run both full suites; check that no test needs network beyond `127.0.0.1` or a cloud account.
  3. Decide O8 (app tests in CI) with the maintainer; if yes, add a second step with
     `working-directory: benchmarks/app`, and close O8 in `design.md`.
- **Verify:** `cd benchmarks && uv run pytest -q`; `cd benchmarks/app && uv run pytest -q`; the PR's `unit-tests`
  job shows the new step passing.

## Iteration 11: Sync docs and skills

- `AGENTS.md:28-49` (Repo map): add a `benchmarks/` line next to `e2e/` (`ak-bench` harness + benchmarked app, see
  `benchmarks/README.md`).
- `.agents/skills/ak-dev-testing-conventions/SKILL.md:531` (`test-reusable.yaml` description): add that `unit-tests`
  also runs `uv run pytest` in `benchmarks/` (and `benchmarks/app/` if O8 is yes).
- No update needed (checked):
  - `.agents/skills/ak-dev-code-quality/SKILL.md:305` and `docs/docs/core-concepts/configuration.md:368` describe the
    `TRACE` level from #911; this issue doesn't change it.
  - `ak-dev-architecture`: the harness is outside the `agentkernel` package and adds no AK component.
  - Docs website and bundled skills (`ak-py/src/agentkernel/skills/`): the benchmark is an AK-team tool, not a user
    feature.
  - `Scratches/25.Benchmarking-Design/testing-checklist.md` and #786 `design.md` already cover `--force-unlock`.
- Run the `ak-dev-sync-docs-from-branch` and `ak-dev-sync-skills-from-branch` flows before merge to confirm.
