---
name: ak-dev-bench-change-harness
description: >
  Step-by-step guide for adding a feature to the shared code of the ak-bench benchmark harness (benchmarks/), i.e.
  anything that is not a new fetcher, host or client driver: a new kind of measured data (a sixth fetcher family),
  a new CSV column or file, a new graph, an ak-bench.yaml key, a CLI command or flag, a change to the step flow or
  load generation, a state.json / deployment.json field, or a change to the benchmarked app (benchmarks/app/). Use
  this skill when asked to "add <feature> to the benchmark". Covers research, the design update, the touch points
  per kind of change, keeping existing results and configs working, tests and docs.
license: Apache-2.0
metadata:
  author: yaalalabs
  category: developer
---

# Changing the ak-bench Harness (Shared Code)

These changes touch code every host and mode shares, so a mistake breaks every benchmark, not one host. Load
`ak-dev-bench-architecture` first and follow its end-to-end workflow (baseline, research, decide or ask, implement,
verify, docs, report) and its "never break existing results or configs" rules.

First check that it really isn't a plug-in: a new data source for an existing family is `ak-dev-bench-new-fetcher`,
a new place to deploy is `ak-dev-bench-new-host`, a new mode is `ak-dev-bench-new-client-driver`.

## Step 0: Research and design

- **Is it in scope?** The benchmark records and reports only. A feature that judges results (pass / fail,
  thresholds, alerts, early stops because results look bad, auto-adjusting load or deployments) is out of scope;
  tell the person instead of building it. (Phase 2 SLA checks are a planned exception in the #786 design; build them
  only from that section.)
- **What does the #786 design say?** Read the sections the feature touches (`docs/specs/786-benchmark-system/
  design.md`: Step timeline, Throughput and latency, Scaling, Resource usage, Cost, Results, Graphs, Later). If the
  feature is listed under "Later" or "Phase 2", build it as described there.
- **Research what it needs**: for measured data, the fetcher skill's research per platform (every built-in host
  must be able to provide it, or the design must say what an unsupported host records: empty columns); for
  statistics (percentiles, windows, rates), the method and its edge cases (empty input, one sample, gaps); for
  graphs, what question the graph answers and from which CSV columns. Follow the research rules in the
  architecture skill.
- **Write the design change** into #786 (requirements in point form, matching the document) before the code. A
  change to what is measured or reported is the person's decision: describe it and ask before building, unless the
  request already said exactly that.

## Step 1: Find every touch point

Use the table, then `grep` every name you change across `benchmarks/` (code, tests, README, example yaml) to find
the rest.

| Change | Code | Tests | Docs |
|---|---|---|---|
| `ak-bench.yaml` key | the model in `config.py` (`extra="forbid"`; a default unless required; validate ranges with pydantic or in a method that raises `BenchConfigError` naming the key); the code that reads it; `StepMetadataWriter` if a step ran with it | `tests/test_config.py` (`test_defaults_equal_786_example` compares the defaults with the example yaml; `test_example_file_loads`); a test of the behaviour | `ak-bench.example.yaml` (every key with its default), README config table, #786 Benchmark project |
| Column in `per-request.csv` | `results/csv/per_request.py` (`COLUMNS`, `_row`) | `tests/results/test_results.py` | #786 Results |
| Column in `per-time-window.csv` | `results/csv/per_window.py` (or `scaling_columns.py` / `resource_columns.py`); lay the column out even when there is no data (empty cells), as the existing collectors do | `tests/results/test_results.py`, fixtures in `tests/fixtures/step/` | #786 Results |
| New CSV or JSON file | its writer under `results/`; paths only through `ResultsLayout` (`results/common/layout.py`); CSV writes through `KeyedCsv` (keyed upsert, thread-safe, temp-file write); JSON through `JsonFile` | `tests/results/` | #786 Results (folder layout) |
| New graph | `results/graphs/step_graphs.py` (`StepPlots.draw`) or `cost_graph.py`, using the `Plots` helpers; draw from CSVs only (never from live objects), so `plot` can re-draw old runs; each graph through `Plots.save` (a failing graph is logged, the others still draw); empty data must still draw (`no_data`) | `tests/results/test_plots.py`, including empty CSVs | #786 Graphs |
| New kind of data (sixth family) | `fetchers/core/<family>.py`: result dataclass(es), a family base with `result_type`, `store()` via `KeyedCsv` keyed so a re-stored row replaces the old one, `is_settled()` / `has_value()` only if meaningful; `StageFetchers.validate()` rules if the family has list constraints; a columns collector in `results/csv/` and `PerWindowWriter`; graphs | a scripted mock in `tests/mocks/fetchers.py`, `mock_host()`, `tests/fetchers/core/` (store, settle, has_value) | #786 Hosts + the new section; the fetcher skill's family table and the architecture skill's family table |
| CLI command or flag | a `Command` subclass in `run/commands.py` (holds `DeploymentLock` for any deployment it touches, logs to the run log, raises `BenchError` subclasses); parser and `match` in `cli.py` | `tests/run/test_commands.py`, `tests/run/test_teardown_guarantee.py` if it deploys or tears down | README Commands table, #786 Selecting what to run |
| Step flow / timing | `run/step_runner.py`, `run/step_end_check.py`, `load/generator.py`, `load/schedule.py`; record any new time in `StepRecord`, `state.json` `steps`, `step-metadata.json` | `tests/run/test_step_runner.py`, `test_step_end_check.py`, `tests/load/` | #786 Step timeline / Load generation |
| `state.json` field | `run/state.py`, the writing command; read with `.get()` and a default so older deployments still load | `tests/run/test_state_and_lock.py` | #912 spec State |
| `deployment.json` field | `hosts/host.py` `Deployment` (keep `from_json` accepting files without it), every deployment folder's `deploy.sh` | `tests/run/`, the mock deploy folder `tests/mocks/deploy/` | `benchmarks/app/deploy/README.md`, #786 Deployment folders |
| Benchmarked app | `benchmarks/app/` (`mock_agent.py`, `identity.py`, `agent.py`, `config.yaml`); token format changes on both sides (`load/token.py` and `app/identity.py`) | `benchmarks/app/tests/`, `tests/load/test_token_cross_check.py` | `benchmarks/app/README.md`, #786 Mock agent |
| New `TraceStage` / trace point | an AK change in `ak-py` (`core/logger.py`, the handler that logs it): follow `ak-dev-architecture` and `ak-dev-testing-conventions`, separate from the harness change | `ak-py` tests | #786 AK change section, `docs/` for the TRACE level |

## Step 2: Implement

- Smallest complete change; reuse the existing helpers (`KeyedCsv`, `ResultsLayout`, `JsonFile`, `WindowGrid`,
  `percentiles`, `Plots`, `FetcherInvoker`, `RunLog`) instead of new ones.
- Keep the role split: only `fetchers/` calls a platform SDK; `results/` only reads and writes files; `run/` runs
  commands and steps; `load/` only talks to the app. No `if host == ...` or `if platform == ...` anywhere.
- Errors: raise a `BenchError` subclass from `errors.py` with a message naming the thing (key, path, deployment id)
  so the CLI exits 1 with it; catch broadly only where the harness already does (fetcher calls, single graphs).
- Times: timezone-aware UTC wall clock for windows, `time.monotonic()` for durations (see `load/generator.py`).
- Concurrency: fetchers run in worker threads and the load generator on one event loop; shared state needs the
  existing locks (`KeyedCsv` per-path lock, `state.json` `flock`).
- Follow `ak-dev-code-quality` (classes over script-style functions, one-line section comments, no unrequested
  edits) and `ak-dev-testing-conventions`.

## Step 3: Verify that nothing broke

- Both suites green against the baseline; ruff check and format clean on your files.
- Old results still work: run `plot` (or the `StepPlots` / `PerWindowWriter` tests) on the recorded fixtures in
  `tests/fixtures/step/` and a results folder made before your change, if one exists locally.
- An old `state.json` without your new keys still loads in every command.
- An `ak-bench.yaml` without your new key still loads (unless the key is required by design).
- `grep` every renamed or touched name: no consumer left behind.

## Checklist

- [ ] In scope (record and report only); #786 design updated first; the person agreed to any change in what is
      measured or reported
- [ ] Research recorded with sources; edge cases (no data, one sample, failures) decided
- [ ] Every touch point in the table handled; nothing renamed or removed
- [ ] Old results, old `state.json` and old configs still work
- [ ] Tests added; both suites green; ruff clean
- [ ] README, example yaml, deploy README and the `ak-dev-bench-*` skills updated where the change affects them
