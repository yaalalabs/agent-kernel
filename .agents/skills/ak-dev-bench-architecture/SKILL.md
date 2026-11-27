---
name: ak-dev-bench-architecture
description: >
  Map of the ak-bench benchmark harness (benchmarks/): how a run flows (deploy, step, plot, finish, post-run),
  where each piece of code lives (fetchers/, hosts/, load/, run/, results/, app/deploy/), the extension seams
  (fetchers, hosts, deployment folders, client drivers) and the rules every change to the harness follows
  (record and report only, the harness never calls a cloud API, built-ins only, stateless fetchers). Use this
  skill before changing or extending ak-bench: it holds the end-to-end workflow (baseline, research, implement,
  verify, docs, report) every ak-bench change follows, and picks the step-by-step skill: ak-dev-bench-new-fetcher,
  ak-dev-bench-new-host, ak-dev-bench-new-client-driver or ak-dev-bench-change-harness.
license: Apache-2.0
metadata:
  author: yaalalabs
  category: developer
---

# ak-bench Harness Architecture

`benchmarks/` is the AK team's benchmark harness (`ak-bench` CLI) and the app it deploys (`benchmarks/app/`). It is
its own uv project, not part of the `agentkernel` package, and imports only AK's public API (`agentkernel.core`,
`agentkernel.identity`, `agentkernel.secret`, `agentkernel.<framework>`), never AK internals.

Design sources (read the section you touch before changing it):

- `docs/specs/786-benchmark-system/design.md`: the system design (what is measured, the run flow, hosts, client
  drivers, deployment folders, results, graphs). Its `research/` folder has the per-platform research.
- `docs/specs/912-ak-benchmark-harness/`: `design.md`, `spec.md`, `plan.md` for the harness core as built.
- `benchmarks/README.md`: commands and every `ak-bench.yaml` key.
- `benchmarks/app/deploy/README.md`: the deployment-folder script contract.

## Which skill for which change

| You want to add | Skill | What changes |
|---|---|---|
| A new way to read scaling, CPU / memory, queue depth, trace lines or cost from a platform | `ak-dev-bench-new-fetcher` | One file under `fetchers/<platform>/<family>/`, plus a line in a host |
| A new place AK runs (EKS, Cloud Run, Azure Container Apps, ...) | `ak-dev-bench-new-host` | Entries in `hosts/<platform>.py`, one deployment folder per mode × message type |
| A new execution mode or message type (WebSocket streaming, REST async, ...) | `ak-dev-bench-new-client-driver` | One driver file in `load/driver/`, a factory branch, a deployment folder per host |
| Any other feature: a new kind of data, CSV column, graph, config key, command, step-flow change, app change | `ak-dev-bench-change-harness` | Shared code in `fetchers/core/`, `results/`, `run/`, `load/`, `config.py`, `cli.py` or `app/` |

Most new hosts need new fetchers first, and every new host or driver needs deployment folders; the host skill covers
the folders.

A new platform (GCP, Azure, Kubernetes) is the fetcher skill for each source it needs, then the host skill. A new
transport (Pub/Sub, Kafka) is a `TransportCollector` fetcher plus the deployment folders that use it.

Anything that isn't one of these plug-ins changes code every host shares: use `ak-dev-bench-change-harness`.
Anything that judges results (thresholds, alerts, auto-tuning) is out of scope: see the rules below.

## How to do an ak-bench change end to end

The person asking may only say "add the GKE host" or "add per-request CPU". The agent does the whole change, and
it must be correct and must not break what exists. Every `ak-dev-bench-*` skill follows these stages:

1. **Understand and scope.** Restate what will be measured or changed and which skill(s) apply. Read the #786
   design sections the change touches and the code you will change (and its callers and tests).
2. **Baseline.** Before editing, run `cd benchmarks && uv run pytest -q` and `cd benchmarks/app && uv run pytest -q`
   and note any failure that already exists, so you neither hide nor get blamed for it.
3. **Research** (each skill lists what to find out for its kind of change). Rules:
   - Verify every external fact (API names and fields, metric names, resolutions, publish delays, quotas, limits,
     defaults, pricing and billing rules, required permissions) in the **official** docs (AWS, Google Cloud,
     Microsoft Learn, kubernetes.io, the library's own docs), and check it is current. Never write these from
     memory; earlier drafts of this design had several wrong cloud facts written that way.
   - Facts about this repo (AK frame shapes, TRACE points, Terraform defaults, Helm values) come from the code:
     read it and cite `file:line`.
   - Compare the options, don't stop at the first one that works: for each, what it gives, what it costs, its
     limits, and what it needs set up. Pick the one that best serves what the #786 design measures and say why the
     others lost.
   - Record the findings with their source links in `docs/specs/786-benchmark-system/research/` (the file for that
     topic, or a new one listed in its README). Write "not verified" against anything you couldn't confirm, and add
     values that can only be measured on a real run to the #786 "Check on the first runs" section.
4. **Decide, or ask.** Make the ordinary choices yourself, following the design. Ask the person only when the
   choice is really theirs: two options are equally good but measure different things, the change alters what the
   benchmark measures or reports, or it costs money (a real cloud deploy, a paid feature such as Container
   Insights). Never run `deploy` / `run` against a real cloud account without the person's go-ahead.
5. **Implement** the smallest complete change with the step-by-step skill. Reuse what exists; touch shared code only
   when the skill says it's needed.
6. **Verify.**
   - Both test suites green (and no new failure compared to the baseline), new tests for the new code, ruff check and
     format clean on the files you changed (format only your own files).
   - Search for every consumer of anything you changed (`grep` the name across `benchmarks/`) and confirm each still
     works.
   - Go through the skill's checklist item by item.
   - Cloud code you couldn't run: say so plainly. The by-hand cloud run is the person's step unless they ask you to
     run it.
7. **Docs.** The #786 design (and its research notes), `benchmarks/README.md`, `ak-bench.example.yaml`,
   `benchmarks/app/deploy/README.md` as the change needs, and this skill set if a rule changed. If a local
   `Scratches/25.Benchmarking-Design/` folder exists (not in git), it is the main design folder: read its
   `AGENT-INSTRUCTIONS.md` and update it together with #786.
8. **Report.** What changed (files), what the research found and the sources, what was decided and why, what was
   not verified, and what the person must do (cloud prerequisites, the first real run).

**Never break existing results or configs.** People keep `results/` folders and re-plot them later, and the graphs
and analysis read the files by name:

- Don't rename or remove a CSV file, a CSV column, a `state.json` / `deployment.json` / metadata key, a fetcher
  name (it keys CSV columns and `fetchers.<name>`), a host name, a mode or message type, or a CLI flag. Add new ones
  next to them.
- Read new `state.json` keys with `.get()` and a default, so a deployment created before the change still works
  with `step`, `plot`, `finish` and `post-run`.
- A new `ak-bench.yaml` key gets a default unless the design says it's required.

## Run flow

```
deploy   -> HostRegistry.get(host) validates the host's fetcher lists, DriverFactory checks mode x message type,
            fetchers.<name> keys are checked, the deployment folder must exist  (all before any script runs)
         -> app/deploy/<host>-<mode>-<message-type>/deploy.sh writes deployment.json -> Deployment, saved in state.json
step     -> StepRunner: every client's ClientDriver connects -> before window (during_step fetchers start polling)
            -> cooldown_checks read their starting values -> LoadGenerator sends load through the drivers
            -> cool-down: every request settled, then each cooldown_checks fetcher settled for its settle_window_s
            -> wait after_step_wait_s -> after_step fetchers once -> per-request.csv, per-time-window.csv, metadata
plot     -> graphs from the step CSVs (and cost.csv)
finish   -> after_all_steps fetchers -> destroy.sh
post-run -> after_teardown fetchers (on AWS: billed cost, ~1 day later) -> re-plot
```

Each command holds the deployment's lock in `state.json`; `run` chains them per host × mode × message type.

## Code layout (split by role, not by topic)

```
ak_bench/
  fetchers/                 the ONLY code that calls a cloud / platform SDK
    core/                   contracts: InfoFetcher + the five family bases and their result dataclasses, StageFetchers
    <platform>/             aws/, later gcp/, azure/, kubernetes/: named after the system the code CALLS, not where AK runs
      common/               shared helpers that aren't contracts (SDK session, log-query helper); only when needed
      <family>/             scaling/, resources/, trace/, transport/, cost/: one file per implementation
  hosts/                    which fetchers each host uses; no fetching code
    host.py                 Host, Deployment, RunInfo
    registry.py             HostRegistry: built-in name -> Host
    <platform>.py           the host bundles of one platform (aws.py, later gcp.py, ...)
  load/                     talks only to the deployed app: LoadGenerator, schedules, token signing
    driver/                 ClientDriver (base.py), DriverFactory (factory.py), one file per mode x message type
  run/                      commands, state.json + lock, deployment-folder scripts, StepRunner, StepEndCheck; no SDK
  results/                  reads stored files, writes CSVs / graphs / metadata; no SDK
app/                        the benchmarked AK app (mock agent, token identity), its own uv project
  deploy/<host>-<mode>-<message-type>/   deploy.sh, destroy.sh, Terraform, entry files
tests/                      mirrors ak_bench/, plus mocks/ (mock fetchers, mock host, MockWsServer, mock deploy folder)
```

Folder rules: a folder is created only when it holds a file (no empty `core/` or `common/`); file names name the
source (`ecs_api.py`), class names stay full (`EcsApiScalingInfoFetcher`); `tests/` mirrors `ak_bench/`.

## The five fetcher families (`fetchers/core/`)

| Family base | Result type (`fetch()` returns) | Stored in | `is_settled()` | `has_value()` |
|---|---|---|---|---|
| `ScalingInfoFetcher` | `ScalingInfo(samples: [CountSample], spans: [WorkerSpan])` | `scaling-samples.csv`, `worker-spans.csv` | every tier's latest `running` == its starting value | any `running` sample |
| `ResourceUsageFetcher` | `ResourceUsage(samples: [ResourceSample])` | `resource-usage.csv` | – | always |
| `TraceCollector` | `TraceInfo(stages: {request_id: {TraceStage: ts}})` | `stage-timestamps.csv` | – | always |
| `TransportCollector` | `QueueInfo(samples: [QueueDepth])` | `queue-depth.csv` | every queue's latest `waiting == in_flight == 0` | any sample |
| `CostFetcher` | `CostInfo(items: [CostItem])` | `cost.csv` | – | always |

The family base writes `store()` (upsert by key through `KeyedCsv`, so a row stored twice is stored once) and, where
it can, `is_settled()`. A platform subclass writes `fetch()` only. Only families with `is_settled()` can sit in
`cooldown_checks`.

## Where a fetcher runs: the host's `StageFetchers` lists

| List | When | `fetch()` window | `results` folder |
|---|---|---|---|
| `during_step` | background, every `poll_interval_s`, start of before → end of cool-down | (last poll, now) | step folder |
| `cooldown_checks` | each cool-down poll, in order; `fetch()` + `is_settled()`, nothing stored | (now − `cooldown_lookback_s`, now) | – |
| `after_step` | once per step, after the cool-down and `after_step_wait_s` | (step start, step end) | step folder |
| `after_all_steps` | `finish`, before teardown | (deploy start, now) | deployment folder |
| `after_teardown` | `post-run` | (deploy start, teardown end) | deployment folder |

The list picks the window; the fetcher never knows which list it is in. One object can be in several lists.

## Rules every change follows

- **Record and report only.** The harness records CSVs and draws graphs. No thresholds, warnings about results,
  early stops, or auto-tuning of load or deployments. (Exceptions already built: the missing-responses `WARNING` per
  step.) The cool-down check reading fetcher values to end a step is part of the flow, not a judgement.
- **Only `fetchers/` calls a cloud or platform SDK.** `run/`, `load/`, `results/` and `hosts/` never do. Deploying
  is not Python: it is the deployment folder's `deploy.sh` / `destroy.sh`.
- **No per-cloud or per-host classes** (`AWSBenchmarker`, `LambdaBenchmarker`). Cloud, compute type and transport vary
  independently: fetchers are grouped by the platform they call, hosts are composed from them.
- **Built-ins only.** No `register()`, no dotted-path bring-your-own: a new host is an entry in `HostRegistry`, a new
  driver a branch in `DriverFactory`. Unknown names fail naming the built-ins.
- **The harness never branches on host type** (serverless vs containerized, AWS vs GCP). It only reads the lists.
- **Fetchers are stateless and thread-safe.** `run` and `deployment` are `fetch()` parameters; nothing per-call is
  kept on `self`.
- **Fetcher names are unique per host.** The name keys the CSV rows and columns, so two fetchers with one name
  overwrite each other's rows. `StageFetchers.validate()` refuses a missing name but does **not** yet refuse a
  duplicate (the design asks for it), so check it yourself.
- **A tier is a key of `deployment.resources`.** Adding a tier is a `deployment.json` change only; fetchers loop over
  tiers and CSVs / graphs lay out columns per tier.
- **Failures never stop the run.** `FetcherInvoker` logs a failing fetcher to the run log and carries on; its columns
  stay empty.
- Follow `ak-dev-code-quality` (classes over script-style functions, one-line section comments) and
  `ak-dev-testing-conventions`.

## Tests and checks

```bash
cd benchmarks && uv run pytest -q          # harness, cloud-free; runs in CI (test-reusable.yaml)
cd benchmarks/app && uv run pytest -q      # the benchmarked app; runs in CI
cd benchmarks && uv run ruff check . && uv run ruff format --check .
```

CI runs only `pytest` for both projects; ruff is not run on `benchmarks/` in CI, so run it yourself. No test may
need a cloud account, a cloud region or network beyond `127.0.0.1`. Test folders have no `__init__.py`, so every
test file name must be unique across `tests/` (pytest refuses two `test_cloudwatch_metric.py` in different folders). Tests register the mock host with
`monkeypatch.setitem(HostRegistry._BUILTINS, "mock", mock_host())` (`tests/mocks/host.py`) and use the scripted mock
fetchers in `tests/mocks/fetchers.py`.

## Docs to keep in sync

- A change to what is measured, a new host, fetcher or driver: update `docs/specs/786-benchmark-system/design.md`
  (Hosts table, Client drivers, the per-platform research) and `benchmarks/README.md` if a command or config key
  changes.
- A new deployment-folder input or output: `benchmarks/app/deploy/README.md` and the #786 Deployment folders section.
- A new extension pattern or a rule learned while building one: update the matching `ak-dev-bench-*` skill.
