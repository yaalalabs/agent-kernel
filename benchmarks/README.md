# ak-bench

Benchmark harness for Agent Kernel (`ak-bench`). It deploys the benchmarked app, sends load to it in steps, records
throughput, latency, scaling, resource usage and cost, and draws graphs. See
[docs/specs/786-benchmark-system/design.md](../docs/specs/786-benchmark-system/design.md) for the system design.

> Status: the command-line options are in place; the commands themselves are still being built (#912).

## Install

```bash
cd benchmarks
uv sync
uv run ak-bench --help
```

Copy [ak-bench.example.yaml](ak-bench.example.yaml) to `ak-bench.yaml` and edit it.

## Commands

A benchmark run is split into commands you can run one at a time (deploy once, run single steps when you choose,
plot, tear down), or all at once with `run`.

| Command | What it does |
|---|---|
| `deploy --host <h> --mode <m> --message-type <t> [--run-id <id>]` | Deploys one host × mode × message type by running its deployment folder's `deploy.sh`. Writes `run-metadata.json` and `state.json`, and prints the **deployment id** `<run-id>-<host>-<mode>-<message-type>`. Starts a new run id unless `--run-id` is given; refuses a host × mode × message type that already has a deployment in that run. If `deploy.sh` fails, runs `destroy.sh` and exits with an error. |
| `step --deployment <id> --test-type steady\|burst --step <N> [--replace]` | Runs one step: before window → load → cool-down → wait and fetch. `--step` must be one of the load steps saved at deploy. Writes `step-<N>/`. Refuses an existing step folder unless `--replace` is given. |
| `step --deployment <id> --force-unlock [--yes]` | Clears a step lock held from **another machine** and runs no step. Use it only once the step on that machine is known to be dead. Prints who held the lock and since when, and asks for confirmation (`--yes` skips the prompt). |
| `plot --deployment <id>` or `--run-id <id>` | Draws every graph from the CSVs of the steps run so far. Run it any time, as often as you like. |
| `finish --deployment <id>` | Runs the host's after-all-steps fetchers, tears down (`destroy.sh`), records the teardown time and says whether `post-run` is needed. If `destroy.sh` fails, exits with an error: resources may be left running. |
| `post-run --deployment <id>` or `--run-id <id>` | Runs the after-teardown fetchers (on AWS: the billed cost, about a day after teardown) and re-plots. Safe to run again. |
| `run [--host <h>]... [--mode <m>]... [--message-type <t>]... [--steps <N>]...` | For each selected host × mode × message type: `deploy` → every step (steady N, then burst N, then the next N) → `plot` → `finish`. Each flag can be repeated; leaving one out means the config's list, else all built-ins. Every `--steps` value must be in `load_steps`. If a step fails or you press Ctrl-C, `finish` still runs; only a second Ctrl-C during teardown skips it (and that is logged). |

Global options (before the command):

| Option | Default | Meaning |
|---|---|---|
| `--config` | `$AK_BENCH_CONFIG_PATH_OVERRIDE`, else `./ak-bench.yaml` | Benchmark config file |
| `--results-dir` | `./results` | Where results go: `results/<run-id>/...`, plus `run.log` per run |
| `--deploy-root` | `benchmarks/app/deploy/` | Folder holding the deployment folders (`<host>-<mode>-<message-type>/`) |

Example, one deployment by hand:

```bash
uv run ak-bench deploy --host ecs --mode async --message-type complete
uv run ak-bench step --deployment <id> --test-type steady --step 1
uv run ak-bench step --deployment <id> --test-type burst --step 1
uv run ak-bench plot --deployment <id>
uv run ak-bench finish --deployment <id>
uv run ak-bench post-run --deployment <id>    # later, once the bill is in
```

## Configuration (`ak-bench.yaml`)

[ak-bench.example.yaml](ak-bench.example.yaml) lists every key with its default. Unknown keys are refused, naming the
key. Any key can also be set by an `AK_BENCH_`-prefixed environment variable, nested keys joined with `__`
(`AK_BENCH_STEP_RUN__TIME_WINDOW_S=5`); it wins over the file.

| Key | Default | Meaning |
|---|---|---|
| `hosts`, `modes`, `message_types` | all built-ins | What `run` selects when the CLI doesn't narrow it |
| `test_types` | `[steady, burst]` | Test types `run` runs per step |
| `load_steps` | `[1, 10, 100, 1000]` | Client counts; saved by `deploy`, so changing them needs a new deploy |
| `step_run.before_window_s` | `60` | Recording time before load starts |
| `step_run.max_cooldown_s` | `2700` | Longest cool-down before the step ends anyway |
| `step_run.after_step_wait_s` | `60` | Wait before the after-step fetch |
| `step_run.client_timeout_s` | `300` | A request with no reply by then is a timeout |
| `step_run.time_window_s` | **required** | Width of one row in `per-time-window.csv` |
| `step_run.cooldown_poll_interval_s` | `10` | Time between two cool-down polls |
| `step_run.cooldown_lookback_s` | `180` | How far back each cool-down check reads |
| `steady_traffic.min_send_interval_s` / `max_send_interval_s` | `1` / `5` | Random gap between a client's requests (steady) |
| `steady_traffic.load_time_s` | `300` | How long steady load is sent |
| `fetchers.default.poll_interval_s` | **required** | Poll interval of a during-step fetcher not listed by name |
| `fetchers.<name>.poll_interval_s` | | Poll interval for the fetcher `<name>`; an unknown name is refused before deploy |
| `host_settings.<host>.max_cooldown_s` | | Overrides `step_run.max_cooldown_s` for that host; other keys go to `deploy.sh` |
| `mock_agent.min_delay` / `max_delay` | | Both set: mock agent sleeping a random delay in [min, max]. Block left out: real agent. Only one set, a negative value, or min > max: `deploy` refuses |

## Tests

```bash
cd benchmarks
uv run pytest -q
```
