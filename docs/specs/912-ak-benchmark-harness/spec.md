# #912: Benchmark harness (`ak-bench` core) — Implementation Spec

Builds the cloud-independent part of the #786 benchmark system: a new top-level `benchmarks/` uv project with the
`ak_bench` package and its `ak-bench` console script, plus the benchmarked app in `benchmarks/app/` (its own uv
project). The design idea: every platform-specific read is an `InfoFetcher` placed in one of a host's five lists, every
deployment is a folder of scripts, and everything else (load, timing, step flow, CSVs, derived numbers, graphs) is
shared code that only sees the ABCs, so the AWS issues under #917 add fetchers, a registry entry and deployment folders
with no harness change.

[`design.md`](design.md) is the requirements source; the system design is
[`docs/specs/786-benchmark-system/design.md`](../786-benchmark-system/design.md) ("#786" below). This spec adds the
class structure, file formats and algorithms. Details that `design.md` leaves open and this spec decides are collected
in [Decisions made while detailing](#decisions-made-while-detailing) for the reviewer.

## Design

### Project layout

```
benchmarks/
├── pyproject.toml              # project "ak-bench", console script ak-bench, path source on ../ak-py
├── uv.lock
├── README.md                   # how to install, run the tests, and the ak-bench.yaml reference
├── ak-bench.example.yaml       # every key of #786 Benchmark project, with the defaults
├── ak_bench/
│   ├── __init__.py
│   ├── cli.py                  # BenchCli: argparse front end, one sub-command per command class
│   ├── config.py               # BenchConfig and its sub-models, BenchConfigError
│   ├── errors.py               # BenchError and its subclasses
│   ├── hosts.py                # HostRegistry (built-in names only; empty in this issue)
│   ├── platforms/
│   │   └── base.py             # dataclasses, InfoFetcher, the five families, Fetchers, Deployment, Host, RunInfo
│   ├── load/
│   │   ├── records.py          # RequestRecord, ResponseEvent, RequestStatus
│   │   ├── driver/             # client drivers, one file per mode × message type (AK's base / factory / impl layout)
│   │   │   ├── base.py         # ClientDriver ABC
│   │   │   ├── factory.py      # DriverFactory (built-ins only)
│   │   │   └── ws_complete.py  # WebSocketCompleteDriver
│   │   ├── token.py            # TokenSigner
│   │   ├── schedule.py         # BurstSchedule, SteadySchedule
│   │   └── generator.py        # LoadGenerator, LoadResult
│   ├── run/
│   │   ├── commands.py         # Deploy, Step, Plot, Finish, PostRun, Run
│   │   ├── state.py            # DeploymentState, StepLock, StepWindow
│   │   ├── deployment_folder.py  # DeploymentFolder: finds and runs deploy.sh / destroy.sh
│   │   ├── step_runner.py      # StepRunner, StepRecord
│   │   ├── fetcher_invoker.py  # FetcherInvoker: fetch_and_store with failure → run log
│   │   └── run_log.py          # RunLog
│   ├── scaling/
│   │   ├── collector.py        # ScalingCollector (per-window worker / queue columns)
│   │   ├── derived.py          # ScalingDerivation (summary scaling numbers)
│   │   └── step_end.py         # StepEndCheck, StepEnd
│   ├── resources/
│   │   └── collector.py        # ResourceCollector (per-window and summary CPU / memory)
│   ├── cost/
│   │   └── report.py           # CostReport (billed cost graph)
│   └── results/
│       ├── layout.py           # ResultsLayout: every path under results/
│       ├── keyed_csv.py        # KeyedCsv: thread-safe upsert-by-key CSV file
│       ├── percentiles.py      # PERCENTILES + percentiles() helper
│       ├── per_request.py      # PerRequestWriter
│       ├── per_window.py       # PerWindowWriter, WindowGrid
│       ├── summary.py          # SummaryWriter
│       ├── metadata.py         # RunMetadataWriter, StepMetadataWriter
│       └── plots.py            # StepPlots, TestTypePlots
├── app/
│   ├── pyproject.toml          # project "ak-bench-app", package = false, path source on ../../ak-py
│   ├── uv.lock
│   ├── README.md
│   ├── agent.py                # registers MockAgent or the real agent; starts nothing (entry files are per deployment folder)
│   ├── config.yaml             # the app's AK config (below)
│   ├── mock_agent.py           # MockRunner, MockAgent, mock_delays()
│   ├── identity.py             # BenchIdentityProvider
│   ├── tests/                  # test_mock_agent.py, test_identity.py
│   └── deploy/                 # deployment folders: none in this issue (they come with the AWS issues)
└── tests/
    ├── conftest.py             # fixtures below
    ├── mocks/
    │   ├── fetchers.py         # MockScalingFetcher, MockResourceFetcher, MockTraceCollector,
    │   │                       # MockTransportCollector, MockCostFetcher, RaisingFetcher, WrongTypeFetcher
    │   ├── host.py             # mock_host(): a Host built from the mock fetchers
    │   ├── ws_server.py        # MockWsServer: local echo server
    │   └── deploy/mock-async-complete/   # deploy.sh / destroy.sh writing a deployment.json for MockWsServer
    └── test_*.py               # see Testing
```

- The harness package is `ak_bench` (importable name of the `ak-bench` project). `design.md`'s module paths
  (`platforms/base.py`, `run/commands.py`, ...) are relative to it.
- One file per implementation. Module-level functions: only `percentiles()` (results/percentiles.py) and the console
  script entry `main()` (cli.py); see [Module-level functions](#module-level-functions).
- The mock deployment folder lives under `tests/`, not `app/deploy/`, so a real `ak-bench run` can never pick it.
  `DeploymentFolder` takes its root as a parameter (CLI `--deploy-root`, default `benchmarks/app/deploy/`), and the
  tests point it at `tests/mocks/deploy/`.

### Dependencies and tooling

`benchmarks/pyproject.toml`:

```toml
[project]
name = "ak-bench"
version = "0.1.0"
requires-python = ">=3.12,<3.14"           # same range as ak-py (ak-py/pyproject.toml:10)
dependencies = [
    "agentkernel",                          # TraceStage, TraceLine (path source below)
    "pydantic>=2.11.7,<3.0.0",              # same floor as ak-py
    "pyyaml>=6.0.2,<7.0.0",
    "numpy>=2.0,<3.0",
    "matplotlib>=3.9,<4.0",
    "websockets>=13.0,<16.0",               # client driver and the test mock server
]

[project.scripts]
ak-bench = "ak_bench.cli:main"

[dependency-groups]
dev = ["pytest", "pytest-asyncio>=1.2.0,<2.0.0", "ruff==0.17.1"]

[tool.uv.sources]
agentkernel = { path = "../ak-py", editable = true }

[tool.pytest.ini_options]
asyncio_mode = "strict"

[tool.ruff]
line-length = 150
```

- `agentkernel` without extras: `core/logger.py` imports only `core/config.py` (`ak-py/src/agentkernel/core/logger.py:1-9`),
  so no optional SDK is pulled in. No cloud SDK; the AWS issues add `boto3` to this file.
- Pins match ak-py where both use a library (`pydantic`, `pyyaml`, `pytest-asyncio`, `ruff`; `ak-py/pyproject.toml:16,18,194,242`).
- matplotlib is used with the `Agg` backend (set in `plots.py` before `pyplot` is imported), so plotting works headless
  in CI.

`benchmarks/app/pyproject.toml`: like `e2e/app/pyproject.toml` (`package = false`, `requires-python = ">=3.12"`), with
`agentkernel[api,openai]` from the path source `../../ak-py` (the real agent is an OpenAI agent, see
[Mock agent app](#mock-agent-app)); dev group `pytest`, `pytest-asyncio`. The AWS issues add the extras their
packaging needs (`aws`, ...).

### Errors (`errors.py`)

```python
class BenchError(Exception): ...                 # every refusal / failure the CLI turns into exit code 1
class BenchConfigError(BenchError): ...          # ak-bench.yaml and CLI argument problems
class HostRefused(BenchError): ...               # Fetchers.validate() failures
class StepRefused(BenchError): ...               # lock held, folder exists, unknown step, torn-down deployment
class ScriptFailed(BenchError): ...              # deploy.sh / destroy.sh exit code != 0, or missing deployment.json
class FetcherTypeError(BenchError): ...          # fetch() returned another type than the family's
```

- Refusals happen before anything is deployed or any load is sent; each message names the key, path, host or fetcher
  as `design.md` requires.

### Configuration (`config.py`)

`BenchConfig` is loaded the way `AKConfig` is: a `YamlBaseSettingsModified` subclass
(`ak-py/src/agentkernel/core/util/config_yaml_util.py`) reading `ak-bench.yaml` in the working directory (path
override `AK_BENCH_CONFIG_PATH_OVERRIDE`, which `--config` sets) and `AK_BENCH_`-prefixed environment variables, nested
keys joined with `__` (e.g. `AK_BENCH_STEP_RUN__TIME_WINDOW_S`); environment variables win over the file. Read with the
`BenchConfig.get()` singleton (`_reset()` clears it). Every sub-model has `extra="forbid"`, so an unknown key fails
with Pydantic's error, which names the key path (e.g. `step_run.befor_window_s: Extra inputs are not permitted`);
unknown top-level keys of the file are refused by `get()` (AK's YAML source passes on only known keys). `get()` wraps
any `ValidationError` / `yaml.YAMLError` / missing file in `BenchConfigError`.

```python
class StepRunConfig(BaseModel):
    before_window_s: float = 60
    max_cooldown_s: float = 2700
    after_step_wait_s: float = 60
    client_timeout_s: float = 300
    time_window_s: float                     # required: "no default" in #786
    cooldown_poll_interval_s: float = 10     # new key (design.md)
    cooldown_lookback_s: float = 180         # new key (design.md)

class SteadyTrafficConfig(BaseModel):
    min_send_interval_s: float = 1
    max_send_interval_s: float = 5
    load_time_s: float = 300
    # validator: 0 < min <= max, load_time_s > 0

class FetcherSettings(BaseModel):
    poll_interval_s: float                   # > 0

class FetchersConfig(RootModel[dict[str, FetcherSettings]]):
    # validator: "default" must be present (fetchers.default.poll_interval_s is required)
    def poll_interval_for(self, name: str) -> float: ...   # fetchers.<name>, else fetchers.default
    def check_names(self, known: set[str]) -> None: ...    # every key except "default" in known, else BenchConfigError

class HostSettings(BaseModel):
    model_config = ConfigDict(extra="allow")  # host-specific keys (e.g. lambda_insights) go to deploy.sh as JSON
    max_cooldown_s: float | None = None

class MockAgentConfig(BaseModel):
    min_delay: float | None = None
    max_delay: float | None = None
    def delays(self) -> tuple[float, float] | None: ...    # the mock_agent rules below

class BenchConfig(YamlBaseSettingsModified):
    yaml_file_env_var = "AK_BENCH_CONFIG_PATH_OVERRIDE"; yaml_file_default = "ak-bench.yaml"
    model_config = SettingsConfigDict(env_prefix="AK_BENCH_", env_nested_delimiter="__", extra="forbid", env_ignore_empty=True)

    hosts: list[str] | None = None           # None = every registered host
    modes: list[str] | None = None           # None = every mode with a driver
    message_types: list[str] | None = None   # None = every message type with a driver
    test_types: list[Literal["steady", "burst"]] = ["steady", "burst"]
    load_steps: list[int] = [1, 10, 100, 1000]   # validator: non-empty, each >= 1, no duplicates
    step_run: StepRunConfig
    steady_traffic: SteadyTrafficConfig = SteadyTrafficConfig()
    fetchers: FetchersConfig                 # required (default.poll_interval_s has no default)
    host_settings: dict[str, HostSettings] = {}
    mock_agent: MockAgentConfig | None = None

    def max_cooldown_for(self, host: str) -> float: ...    # host_settings.<host>.max_cooldown_s, else step_run's
    @classmethod
    def get(cls) -> "BenchConfig": ...    # singleton; refuses unknown top-level keys; errors → BenchConfigError
    @classmethod
    def _reset(cls): ...
```

- **Required keys:** `step_run.time_window_s` and `fetchers.default.poll_interval_s`. A file without them fails at load
  with the key path in the message.
- **`fetchers.<name>` check:** `FetchersConfig.check_names(known)`, where `known` is the union of `f.name` over every
  list of every selected host. Called by `Deploy` and `Run` after the hosts are resolved, before any script runs.
  Message: `fetchers.aws.ecs-api: no fetcher of the selected hosts has this name; known: aws.ecs_api, sqs`.
- **`mock_agent` rules** (`MockAgentConfig.delays()`, called by `Deploy` before anything runs; a missing block is
  `None` → real agent):

  | `min_delay` | `max_delay` | Result |
  |---|---|---|
  | set | set | `(min, max)` → mock agent |
  | unset | unset | `None` → real agent |
  | one set | | `BenchConfigError("mock_agent.max_delay is missing ...")`, naming the missing key |
  | `< 0`, or `min > max` | | `BenchConfigError` naming the key (`mock_agent.min_delay`) |

  Checked in `delays()` rather than a Pydantic validator, because `design.md` makes it a `deploy` refusal; `step`,
  `plot` and `post-run` load the same file and must not fail on it.
- **CLI vs config (#786 L3):** both stay. A CLI value (`run --host`, `--mode`, `--message-type`, `--steps`) narrows the
  config's list; `step --test-type` and `step --step` are single values. Nothing is dropped in this issue.

### Registries

**Host registry (`hosts.py`):**

```python
class HostRegistry:
    _BUILTINS: ClassVar[dict[str, Host]] = {}      # ecs / lambda are added by the AWS issues

    @classmethod
    def get(cls, name: str) -> Host: ...           # unknown → BenchConfigError("unknown host 'x'; built-ins: ...")
    @classmethod
    def names(cls) -> list[str]: ...
```

- No `register()` method and no dotted-path branch (built-ins only, `design.md` Registries). Tests add the mock host
  with `monkeypatch.setitem(HostRegistry._BUILTINS, "mock", mock_host())`.
- `get()` calls `host.fetchers.validate(name)` before returning, so every command that loads a host validates it
  before deploying anything.

**Driver factory (`load/driver/factory.py`):**

```python
class DriverFactory:
    BUILTINS: ClassVar[tuple[tuple[str, str], ...]] = (("async", "complete"),)

    @staticmethod
    def driver_class(mode: str, message_type: str) -> type[ClientDriver]:
        if (mode, message_type) == ("async", "complete"):
            return WebSocketCompleteDriver
        raise BenchConfigError(f"no client driver for {mode} + {message_type}; built-ins: async + complete")
```

- `BUILTINS` supplies the `modes` / `message_types` defaults. A later driver is one more branch and one more tuple.

### Platform base (`platforms/base.py`)

Dataclasses (fields as in #786 and `Scratches/25.Benchmarking-Design/implementation/code-layout.md`; all timestamps are
timezone-aware UTC `datetime`s):

```python
@dataclass(frozen=True)
class RunInfo:                      # the `run` argument of fetch(): who is running, never results
    run_id: str
    deployment_id: str              # "<run-id>-<host>-<mode>-<message-type>", also the cloud tag value
    host: str
    platform: str
    mode: str
    message_type: str

@dataclass
class Deployment:                   # read from deployment.json, saved in state.json unchanged
    endpoint: str
    resources: dict[str, dict[str, Any]]
    queues: dict[str, dict[str, Any]]      # keys "input", "output"
    logs: dict[str, str]
    settings: dict[str, Any]
    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Deployment": ...   # missing key → ScriptFailed naming it
    def to_json(self) -> dict[str, Any]: ...

@dataclass
class CountSample:   ts: datetime; tier: str; count_type: str; value: int
@dataclass
class WorkerSpan:    tier: str; worker: str; started: datetime; stopped: datetime | None; extra: dict = field(default_factory=dict)
@dataclass
class ScalingInfo:   samples: list[CountSample] = ...; spans: list[WorkerSpan] = ...

@dataclass
class ResourceSample: ts: datetime; tier: str; worker: str | None; metric: str; stat: str; value: float
@dataclass
class ResourceUsage:  samples: list[ResourceSample] = ...

@dataclass
class TraceInfo:      stages: dict[str, dict[TraceStage, datetime]] = ...   # {request_id: {stage: ts}}

@dataclass
class QueueDepth:     ts: datetime; queue: str; waiting: int; in_flight: int
@dataclass
class QueueInfo:      samples: list[QueueDepth] = ...

@dataclass
class CostItem:       period_start: datetime; period_end: datetime; service: str; usd: float; metric: str
@dataclass
class CostInfo:       items: list[CostItem] = ...
```

**`InfoFetcher[T]`:**

```python
class InfoFetcher(ABC, Generic[T]):
    name: str                                   # registered name; class attribute or set in __init__
    result_type: ClassVar[type]                 # set once per family base

    def __init__(self, poll_interval_s: float | None = None, settle_window_s: float = 0): ...

    @abstractmethod
    def fetch(self, run: RunInfo, deployment: Deployment, start: datetime, end: datetime) -> T: ...
    @abstractmethod
    def store(self, result: T, results: Path) -> None: ...

    def is_settled(self, now: T, start: T | None) -> bool:
        raise NotImplementedError               # only ScalingInfoFetcher / TransportCollector override it

    def has_value(self, result: T) -> bool:
        return True                             # overridden by the two cooldown families

    def fetch_and_store(self, run, deployment, start, end, results: Path) -> None:
        result = self.fetch(run, deployment, start, end)
        if not isinstance(result, self.result_type):
            raise FetcherTypeError(f"fetcher '{self.name}': fetch() returned {type(result).__name__}, "
                                   f"expected {self.result_type.__name__}")
        self.store(result, results)
```

- `fetch()` is synchronous (it runs in a worker thread, see [Step runner](#step-runner-runstep_runnerpy)).
- `results` is a directory: the step folder for the step lists, the host × mode × message type folder for
  `after_all_steps` / `after_teardown`.
- `is_settled(now, start)` receives `start=None` when the starting read failed; both implementations return `False`
  then (`design.md`: not met until the maximum cool-down).
- `has_value(result)` exists so `StepEndCheck` can tell "read returned no value" (not met + run-log entry) apart from
  "read returned a value that is not settled" without reading the result type itself.

**Family bases** (each sets `result_type` and writes `store()` once through `KeyedCsv`):

| Family | `store()` file, columns | Key (row replaced on a match) | `is_settled(now, start)` | `has_value()` |
|---|---|---|---|---|
| `ScalingInfoFetcher` | `scaling-samples.csv` `ts, tier, count_type, value, fetcher`; `worker-spans.csv` `tier, worker, started, stopped, extra, fetcher` | `ts, tier, count_type, fetcher`; `tier, worker, fetcher` | `start` not None, and for every tier with a `running` sample in `start`: the latest `running` value in `now` equals the latest in `start` (a tier missing from `now` → False) | any `running` sample |
| `ResourceUsageFetcher` | `resource-usage.csv` `ts, tier, worker, metric, stat, value, fetcher` | `ts, tier, worker, metric, stat, fetcher` | – | – |
| `TraceCollector` | `stage-timestamps.csv` `request_id, stage, ts` | `request_id, stage` | – | – |
| `TransportCollector` | `queue-depth.csv` `ts, queue, waiting, in_flight, fetcher` | `ts, queue, fetcher` | every queue's latest sample (by `ts`) in `now` has `waiting == 0 and in_flight == 0`; `start` unused | any sample |
| `CostFetcher` | `cost.csv` `period_start, period_end, service, usd, metric, fetcher` | `period_start, period_end, service, metric, fetcher` | – | – |

- `ScalingInfoFetcher` also declares `count_types: frozenset[str]`.
- `ResourceUsageFetcher` also declares `metrics: frozenset[tuple[str, str]]`, the `(metric, stat)` pairs it gives
  (e.g. `{("cpu_pct", "max"), ("mem_pct", "max")}`). Used only to lay out empty columns for a fetcher that stored
  nothing (see [Per-time-window CSV](#per-time-window-csv-resultsper_windowpy)), the same way `count_types` does for
  scaling.
- Value formats in every CSV: datetimes as ISO 8601 UTC with milliseconds and `Z`
  (`2026-11-23T10:04:00.000Z`, the AK trace-line format); `None` as an empty cell; `extra` as compact JSON.

**`KeyedCsv` (`results/keyed_csv.py`):**

```python
class KeyedCsv:
    _locks: ClassVar[dict[Path, threading.Lock]] = {}
    _locks_guard: ClassVar[threading.Lock] = threading.Lock()

    def __init__(self, path: Path, columns: list[str], key: list[str]): ...
    def upsert(self, rows: Iterable[dict[str, Any]]) -> None: ...   # read, replace/add by key, write temp, os.replace
    def read(self) -> list[dict[str, str]]: ...
```

- **Concurrency contract:** one `threading.Lock` per resolved path, shared by every `KeyedCsv` in the process, held for
  the whole read-modify-write. `during_step` tasks run in parallel worker threads (`asyncio.to_thread`) and two
  fetchers of the same family write the same file, so this is the guarantee `design.md` asks for ("safe when two
  fetchers write the same file at once"). Cross-process safety is not needed: the step lock allows one step process
  per deployment.
- Writes go to `<file>.tmp` then `os.replace`, so a run stopped mid-write leaves the previous complete file.
- Row order: rows keep their first-insert order; new rows are appended.
- **Per-operation cost:** each upsert rewrites the file. A `during_step` poll adds a handful of rows to a file that
  grows to (step seconds ÷ poll interval) × tiers rows, i.e. thousands, not millions; accepted.

**`Fetchers` and `Host`:**

```python
@dataclass
class Fetchers:
    during_step: list[InfoFetcher] = field(default_factory=list)
    cooldown_checks: list[InfoFetcher] = field(default_factory=list)
    after_step: list[InfoFetcher] = field(default_factory=list)
    after_all_steps: list[InfoFetcher] = field(default_factory=list)
    after_teardown: list[InfoFetcher] = field(default_factory=list)

    def all(self) -> list[InfoFetcher]: ...     # every distinct fetcher object, first-seen order
    def validate(self, host: str) -> None: ...

@dataclass(frozen=True)
class Host:
    platform: str
    fetchers: Fetchers
```

`Fetchers.validate(host)` raises `HostRefused` naming the host and fetcher when:

1. a fetcher in `cooldown_checks` doesn't override `is_settled()` (`type(f).is_settled is InfoFetcher.is_settled`);
2. a `ScalingInfoFetcher` in `cooldown_checks` doesn't have `"running"` in `count_types`;
3. a fetcher in any list has no non-empty `name` (added: the name is the CSV column and config key, so a nameless
   fetcher is refused at load rather than failing mid-step).

### Run log (`run/run_log.py`)

```python
class RunLog:
    def __init__(self, path: Path, command: str): ...   # results/<run-id>/run.log
    def info(self, message: str) -> None: ...
    def warning(self, message: str) -> None: ...
    def error(self, message: str) -> None: ...
```

- One line per entry, appended and flushed: `2026-11-23T10:04:00.123Z WARNING step <message>`. Also echoed to stderr
  through `logging.getLogger("ak_bench")`.
- Thread-safe (one lock per instance); fetcher failures are logged from worker threads.

### Results layout (`results/layout.py`)

```python
class ResultsLayout:
    def __init__(self, root: Path, run_id: str): ...
    def run_dir(self) -> Path: ...                                   # <root>/<run-id>/
    def run_log(self) -> Path: ...                                   # <run-id>/run.log
    def deployment_dir(self, platform, host, mode, message_type) -> Path: ...  # state.json, run-metadata.json, cost.csv
    def test_type_dir(self, ..., test_type) -> Path: ...             # summary.csv, graphs/
    def step_dir(self, ..., test_type, step: int, load_steps: list[int]) -> Path: ...
```

- `step-<N>` is zero-padded to `len(str(max(load_steps)))` digits, using the load steps saved in `state.json`
  (e.g. `[1, 10, 100, 1000]` → `step-0001`).
- Folders are created only when written to (only what ran gets a folder).
- `--results-dir` (default `./results`) sets `root`.

### Deployment folders (`run/deployment_folder.py`)

```python
class DeploymentFolder:
    def __init__(self, root: Path, host: str, mode: str, message_type: str): ...
    path: Path                                   # <root>/<host>-<mode>-<message-type>/
    def check(self) -> None: ...                 # folder, deploy.sh, destroy.sh exist → else BenchConfigError naming the path
    def deploy(self, env: ScriptEnv) -> Deployment: ...   # runs deploy.sh, reads <AK_BENCH_OUTPUT>/deployment.json
    def destroy(self, env: ScriptEnv) -> None: ...        # runs destroy.sh

@dataclass(frozen=True)
class ScriptEnv:
    deployment_id: str
    auth_secret: str
    mock_delays: tuple[float, float] | None
    host_settings: dict[str, Any]
    output_dir: Path
    def as_env(self) -> dict[str, str]: ...
```

- Scripts run as `subprocess.run(["bash", script], cwd=folder, env=os.environ | env.as_env())`, stdout / stderr
  inherited (Terraform output stays visible), no timeout.
- `as_env()` sets `AK_BENCH_DEPLOYMENT_ID`, `AK_BENCH_AUTH_SECRET`, `AK_BENCH_HOST_SETTINGS` (JSON of
  `host_settings.<host>`, `{}` when absent), `AK_BENCH_OUTPUT` (the deployment directory), and
  `AK_BENCH_MOCK_AGENT_MIN_DELAY_S` / `AK_BENCH_MOCK_AGENT_MAX_DELAY_S` only for the mock agent. `destroy.sh` gets the
  same variables (Terraform destroy may need the same inputs); after a finished teardown the secret is gone from
  `state.json`, so a second `destroy.sh` gets an empty `AK_BENCH_AUTH_SECRET`.
- Exit code ≠ 0, or no / unreadable `deployment.json` after `deploy.sh` → `ScriptFailed` naming the script and code.
- The script contract (inputs, `deployment.json` fields, Terraform state per deployment id, the auth secret in the
  cloud's secret store and never on a component's environment) is written into `benchmarks/app/deploy/README.md` for
  the AWS issues; the harness does not check what a script does inside.

### State (`run/state.py`)

`state.json` lives in the deployment directory. Schema (all times ISO UTC):

```json
{
  "run_id": "20261123T101500Z", "deployment_id": "20261123T101500Z-ecs-async-complete",
  "host": "ecs", "platform": "aws", "mode": "async", "message_type": "complete",
  "deployment": { "endpoint": "...", "resources": {}, "queues": {}, "logs": {}, "settings": {} },
  "auth_secret": "<hex>",
  "load_steps": [1, 10, 100, 1000],
  "deploy_started": "...", "deploy_finished": "...",
  "steps": { "steady/1": { "started": "...", "before_end": "...", "t_load_up": "...", "t_load_down": "...",
                           "ended": "...", "cooldown_max_reached": false } },
  "lock": { "pid": 4242, "host": "bench-box", "command": "step steady 1", "since": "..." },
  "teardown_at": null
}
```

```python
class DeploymentState:
    @classmethod
    def locate(cls, results_root: Path, deployment_id: str) -> "DeploymentState": ...
    @classmethod
    def create(cls, path: Path, data: dict) -> "DeploymentState": ...   # refuses if the file exists
    @contextmanager
    def update(self) -> Iterator[dict]: ...      # flock on state.json.lock, read, yield, write temp + os.replace
    def read(self) -> dict: ...
    def deployment(self) -> Deployment: ...
    def run_info(self) -> RunInfo: ...

class StepLock:
    def __init__(self, state: DeploymentState, run_log: RunLog, command: str): ...
    def acquire(self) -> None: ...      # StepRefused if held by a live process; takes over a stale one
    def release(self) -> None: ...      # only if this process holds it
    def force_unlock(self, confirm: Callable[[str], bool]) -> None: ...
```

- **Deployment id → folder:** the run id never contains `-` (generated as `%Y%m%dT%H%M%SZ`; `--run-id` must match
  `^[A-Za-z0-9_]+$`), and host, mode and message type names contain no `-`. So `locate()` splits the id into its four
  parts, gets the platform from `HostRegistry.get(host)`, and opens
  `<root>/<run-id>/<platform>/<host>/<mode>/<message-type>/state.json`. Not found → `BenchConfigError`.
- **File safety:** `update()` takes an exclusive `fcntl.flock` on a sibling `state.json.lock` for the whole
  read-modify-write, so `step` and `--force-unlock` from two terminals can't interleave. `state.json` is created with
  mode `0600` because it holds the auth secret. (`fcntl`: Linux / macOS only; the benchmark is not run from Windows.)
- **Lock rules** (`StepLock.acquire`, inside one `update()`):
  - no lock → take it (`pid`, `socket.gethostname()`, command, now);
  - lock from this machine whose process is gone (`os.kill(pid, 0)` raises `ProcessLookupError`) → stale: take it over
    and log `WARNING took over stale step lock of pid <pid> since <since>`;
  - lock from this machine with a live process, or from another machine → `StepRefused` naming holder and since.
- **`force_unlock`:** prints `step lock held by pid <pid> on <host> since <since> (<command>)`, asks
  `confirm()` (`input()` y/N; `--yes` passes `lambda _: True`), clears the lock, logs a run-log `WARNING`. On a lock
  from this machine with a live process it refuses (that process can be stopped instead); with no lock it says so and
  exits 0.
- **Secret lifetime:** `auth_secret` is written by `deploy` and deleted from `state.json` by `finish` once
  `destroy.sh` exits 0 (`design.md`: not kept after the run).

### Commands (`run/commands.py`)

Each command is a class built by `BenchCli` with the loaded `BenchConfig`, the results root and the deploy root, and
has one `execute(...)` method. `Run` composes the others.

```python
class Deploy:   def execute(self, host, mode, message_type, run_id: str | None) -> str: ...  # returns deployment id
class Step:     def execute(self, deployment_id, test_type, step: int, replace: bool) -> None: ...
                def force_unlock(self, deployment_id, yes: bool) -> None: ...
class Plot:     def execute(self, deployment_id: str | None, run_id: str | None) -> None: ...
class Finish:   def execute(self, deployment_id) -> bool: ...        # returns "post-run needed"
class PostRun:  def execute(self, deployment_id: str | None, run_id: str | None) -> None: ...
class Run:      def execute(self, hosts, modes, message_types, steps) -> None: ...
```

**`Deploy.execute`**, in this order (everything up to step 6 runs before any script):

1. `HostRegistry.get(host)` (validates the fetchers) and `DriverFactory.driver_class(mode, message_type)`.
2. `config.fetchers.check_names(...)` over the selected host's fetchers.
3. `config.mock_agent.delays()` (the mock-agent rules).
4. `DeploymentFolder(...).check()`.
5. Run id: `--run-id` or a new one; refuse (`BenchConfigError`) when `<run-id>/.../<mode>/<message-type>/state.json`
   already exists.
6. Secret: `secrets.token_hex(32)` (32 random bytes).
7. Record `deploy_started`, create `state.json` (no `deployment` yet), run `deploy.sh`.
8. On `ScriptFailed`: run-log `ERROR`, run `destroy.sh` (its own failure is logged, not raised over the first one),
   record `teardown_at`, then raise.
9. Save `deployment`, `deploy_finished`; write `run-metadata.json`; print the deployment id.

**`Step.execute`**:

1. Load the state; refuse if `teardown_at` is set.
2. Refuse a `step` not in the saved `load_steps` (message lists them) or a test type other than `steady` / `burst`.
3. `StepLock.acquire()`; everything after runs in `try / finally: lock.release()` (done, error, `KeyboardInterrupt`).
4. Step folder exists: refuse without `--replace`; with it, delete the folder and the step's `summary.csv` row.
5. `StepRunner.run(...)` → `StepRecord`.
6. Save the step window to `state.json`; write `per-request.csv`, `per-time-window.csv`, the `summary.csv` row,
   `step-metadata.json`; plot the step.
7. A failure in 5–6 leaves the partial folder and no `summary.csv` row (the row is written last).

**`Plot.execute`:** for one deployment, or every deployment under `results/<run-id>/` (found by globbing
`state.json`), draws every step's graphs from its CSVs, every test type's per-step graphs, and the cost graph when
`cost.csv` exists.

**`Finish.execute`:** `FetcherInvoker` runs `after_all_steps` for (deploy start, now) into the deployment directory;
re-plots if any of them stored without error; runs `destroy.sh`; on success records `teardown_at` and deletes
`auth_secret`; prints `post-run needed: <list of after_teardown fetcher names>` or `post-run not needed`. A
`ScriptFailed` is logged as run-log `ERROR "destroy.sh failed (exit <n>): resources may be left running"` and
re-raised (exit code 1). A second `finish` after a failure runs `destroy.sh` again.

**`PostRun.execute`:** for each deployment (one, or every one of the run) with `teardown_at` set: runs
`after_teardown` for (deploy start, teardown end) into the deployment directory, re-plots. Refuses a deployment with
no `teardown_at` (`finish` first). Re-running is safe: rows replace by key.

**`Run.execute`**:

1. Resolve hosts / modes / message types (CLI value, else config list, else all built-ins / driver defaults); check
   each `--steps` value against `config.load_steps` (`BenchConfigError` listing the allowed steps); then for every
   combination run steps 1–4 of `Deploy` as a dry check, so a bad combination is refused before the first deploy.
2. For each host × mode × message type: `Deploy` → for each N in `load_steps` order (or the `--steps` subset, same
   order), for each test type in `config.test_types` order: `Step` → `Plot` → `Finish`.
3. **Teardown guarantee:** steps and plot run inside `try`; on any exception or `KeyboardInterrupt`, `Finish` runs in
   the `finally`. A second `KeyboardInterrupt` while `Finish` runs is caught once to log
   `ERROR "teardown skipped by a second Ctrl-C: <deployment id> may be left running"` and then re-raised. After
   `Finish`, the first exception is re-raised (the remaining combinations are not started).
4. No warm-up step.

**CLI (`cli.py`):** `argparse` with sub-commands `deploy`, `step`, `plot`, `finish`, `post-run`, `run` and the flags of
`design.md` Commands, plus global `--config`, `--results-dir`, `--deploy-root`. `step` has a mutually exclusive
group: (`--test-type`, `--step`, `--replace`) or `--force-unlock [--yes]`; its `--help` text says when to use
`--force-unlock` (only once the step on the other machine is known to be dead). `BenchError` → message on stderr,
exit 1; `KeyboardInterrupt` → exit 130.

### Mock agent app (`benchmarks/app/`)

```python
class MockRunner(Runner):
    def __init__(self):
        super().__init__("MockRunner")
        self._min, self._max = mock_delays()   # read once, at creation

    async def run(self, agent, session, requests) -> AgentReplyAny:
        await asyncio.sleep(random.uniform(self._min, self._max))
        return AgentReplyAny(content={"echo": self._prompt(requests)})

    async def stream(self, agent, session, requests) -> AsyncGenerator[StreamEvent, None]:
        await asyncio.sleep(random.uniform(self._min, self._max))
        # MessageStart, one TextDelta with the echo, MessageEnd (shape of DummyRunner.stream)

    @staticmethod
    def _prompt(requests) -> str: ...     # first AgentRequestText's prompt, "" when none

class MockAgent(Agent):
    def __init__(self):
        super().__init__(AGENT_NAME, MockRunner())
    # get_description / override_system_prompt / attach_tool: as DummyAgent
```

- `Runner` (`ak-py/src/agentkernel/core/base.py:337`) has abstract `run()` (`:491`) and `stream()` (`:574`);
  `Agent` is at `:603`; the shape follows `DummyRunner` / `DummyAgent` (`ak-py/tests/test_pipeline_request_handler.py:35,51`).
- No state on `self` besides the two delays; no timing; nothing written to the session.
- **`mock_delays()` (`mock_agent.py`):** reads `AK_BENCH_MOCK_AGENT_MIN_DELAY_S` / `AK_BENCH_MOCK_AGENT_MAX_DELAY_S`
  (empty counts as unset) → `(min, max)` or `None`. The values come from `ak-bench.yaml` `mock_agent`, already checked
  by `MockAgentConfig.delays()` before `deploy`; the app only refuses exactly one set (`RuntimeError`).
- **`agent.py`:** registers the agent only; it starts nothing, since every host and tier has its own entry
  point (Lambda handlers, ECS `AgentRunner.run` / `AWSWebsocketAPI.run()`), written in the deployment folder's entry
  files that `import agent`. `MockAgent` is registered when `mock_delays()` is set; otherwise the real agent: an
  `OpenAIModule` agent under the same `AGENT_NAME` (OpenAI key from `SecretManager`, as the AWS examples do), instructed to repeat the user's message (so the reply still
  carries the request id, see [WebSocket complete driver](#websocket-complete-driver-loaddriverws_completepy)). Exactly one
  of the two set → the app raises at import (a broken deployment, not a silent real agent; `deploy` already refuses
  this case).
- `Runtime.run` calls the runner (`core/runtime.py:546`) and saves the session after the post-hooks (`:555`), so the
  hooks and the in-memory save stay in the measured `AGENT_START` → `AGENT_DONE` span.
- **`config.yaml`:** `session.type: in_memory`, `logging.ak.level: TRACE`, `execution.mode: async`,
  `execution.message_type: complete`, `identity.provider.type: identity.BenchIdentityProvider` with
  `secret_key: AK_BENCH_AUTH_SECRET`, no hooks. Host-specific keys (transport, `secret.provider.type: aws_ssm`,
  `secret.prefix`, deployment blocks) are set by each deployment folder (env vars / its own config), not here.

### Client authentication

**`BenchIdentityProvider` (`app/identity.py`):**

```python
class BenchIdentityProvider(IdentityProvider):
    name = "bench"
    NAMESPACE = "bench"

    def __init__(self, config: "_IdentityProviderConfig", secrets: SecretManager | None = None):
        key = (config.model_extra or {}).get("secret_key", "AK_BENCH_AUTH_SECRET")
        value = (secrets or SecretManager.current()).get(key, default=None)
        if not value:
            raise AKConfigError(f"identity.provider.secret_key '{key}' has no value; the bench provider needs its signing secret")
        self._secret = value.encode("utf-8")

    async def authenticate(self, credential: str, context: RequestContext | None = None) -> Principal:
        user, dot, signature = credential.rpartition(".")
        if not dot or not user or not signature:
            raise AuthenticationError("malformed bench token")
        expected = hmac.new(self._secret, user.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise AuthenticationError("bad bench token signature")
        return Principal(subject=user, kind="user", provider=self.name, namespace=self.NAMESPACE)
```

- Built by AK's factory through the dotted-path branch, which passes the whole provider block
  (`identity/provider/factory.py:57-59`); the block keeps extra keys (`core/config.py:1489-1490`).
- The secret resolves once at construction through `SecretManager.get` (`secret/manager.py:60`): environment, then
  cache, then the configured provider. On AWS the deployment folder sets `secret.provider.type: aws_ssm`; a set
  `AK_BENCH_AUTH_SECRET` environment variable would win over the store (`core/config.py:1411`), which is why no
  component may set one (a deployment-folder rule, written in `app/deploy/README.md`).
- Missing / empty secret → `AKConfigError` at build (startup error, not a provider refusing everyone). `SecretError`
  from the provider (store unreachable) propagates unchanged.
- `IdentityProvider.authenticate` is the only abstract method (`identity/provider/base.py:61-62`).

**`TokenSigner` (`load/token.py`):**

```python
class TokenSigner:
    def __init__(self, secret: str): ...
    def token(self, user: str) -> str: ...      # f"{user}.{hmac_sha256_hex(secret, user)}"
    @staticmethod
    def user(client: int) -> str: ...           # f"bench-{client}", client numbered 1..N
```

- The signing line is duplicated in the app and the harness on purpose (separate projects); the cross-check test
  imports both (see Testing).

### Load generator and client driver

**Records (`load/records.py`):**

```python
class RequestStatus(StrEnum): OK = "ok"; ERROR = "error"; TIMEOUT = "timeout"

@dataclass
class RequestRecord:
    request_id: str; session_id: str; user_id: str
    scheduled_send: datetime                 # wall clock
    sent: datetime | None = None             # wall clock
    first_chunk: datetime | None = None
    complete: datetime | None = None
    status: RequestStatus | None = None      # None while pending
    sent_mono: float | None = None           # monotonic, for durations
    first_chunk_mono: float | None = None
    complete_mono: float | None = None
    settled_mono: float | None = None        # when status was set (error / timeout time for the windows)
    error: str | None = None
    @property
    def latency_s(self) -> float | None: ...   # complete_mono - sent_mono, ok requests only

@dataclass(frozen=True)
class ResponseEvent:
    request_id: str
    kind: Literal["first_chunk", "complete", "error"]
    wall: datetime
    mono: float
    detail: str | None = None
```

- Wall-clock timestamps are `datetime.now(UTC)`; every duration uses `time.monotonic()`. A wall time for windowing is
  derived as `step_start_wall + (mono - step_start_mono)`, so windows and durations share one monotonic base.

**`ClientDriver` (`load/driver/base.py`):**

```python
class ClientDriver(ABC):
    trace_stages: ClassVar[tuple[TraceStage, ...]]     # request-path stages this mode produces, in order

    def __init__(self, endpoint: str, token: str, on_event: Callable[[ResponseEvent], None]): ...
    @abstractmethod
    async def connect(self) -> None: ...                # opens the connection and starts the receive task
    @abstractmethod
    async def send(self, request_id: str, session_id: str, prompt: str) -> None: ...  # returns once written
    @abstractmethod
    async def close(self) -> None: ...                  # stops the receive task, closes the connection
```

- Sending and receiving are separate: `send()` writes the frame and returns; the receive task calls `on_event` for
  every response event. A mode with no chunks emits `first_chunk` and `complete` with the same timestamps.
- `trace_stages` gives the stage order used for the per-request durations, so a stage a mode never logs is simply not
  in its chain (see [Per-request CSV](#per-request-csv-resultsper_requestpy)).

#### WebSocket complete driver (`load/driver/ws_complete.py`)

- `connect()`: `websockets.connect(<endpoint with ?token=<token> added to its query>)`, then starts the receive task.
  A refused token closes the socket (`pipeline/ws/handler.py:192-212`); `connect()` raises in that case (see below).
- `send()`: one text frame, AK's chat frame (`pipeline/ws/handler.py:215-254`):
  `{"request_id": <id>, "body": {"session_id": <session id>, "prompt": <prompt>}}`. No `route` key: the default chat
  route is taken when `route` is absent (`:226`); on API Gateway the frame goes to the `$default` route
  (`route_selection_expression = "$request.body.route"`, `ak-deployment/ak-aws/serverless/modules/websocket-api-gateway/main.tf:15`),
  which the AWS deployment folders wire to the chat handler.
- Receive task, per JSON frame (only reply frames count, so an unexpected frame ends as `timeout`, never as a false `ok`):
  - `type == "CHAT_QUEUED"`: ignored; it carries the request id but is the acknowledgement (`pipeline/ws/handler.py:275-283`).
  - `type == "CHAT_RESPONSE"`: request id = the frame's `request_id` if present, else the in-flight request id of this
    connection that appears in the frame text. A complete reply body is `{"result": str(reply), "session_id": ...}`
    with no request id (`core/chat_service.py:381,394`); the prompt is the request id and the mock agent echoes it,
    so it appears in `result`. Emits `first_chunk` + `complete`, or `error` when the body has an `error` key (agent
    error reply, `pipeline/agent_runner.py:122,166`).
  - `type == "SYSTEM_RESPONSE"` with an `error` key (permanent delivery failure, `pipeline/response_handler.py:141-146`)
    or `status == "FAILED"` (enqueue failure, `pipeline/ws/handler.py:270,297-298`): emits `error` for the request id
    found the same way.
  - every other frame (other `SYSTEM_RESPONSE`, `STREAM_CHUNK`, unknown types) is ignored; an unmatched reply
    (duplicate delivery, late reply after timeout, an error reply without the id) is logged and dropped; the first match
    wins.
- `trace_stages`: every `TraceStage` except `AGENT_FIRST_CHUNK`, `RESPONSE_POLL_START`, `RESPONSE_FOUND`, in enum order
  (`core/logger.py:16-29`).

**Schedules (`load/schedule.py`):**

```python
class BurstSchedule:
    def offsets(self, client: int) -> list[float]: return [0.0]

class SteadySchedule:
    def __init__(self, min_s: float, max_s: float, load_time_s: float, rng: random.Random): ...
    def offsets(self, client: int) -> list[float]: ...
    # t = 0; out = [0]; loop: t += rng.uniform(min_s, max_s); if t > load_time_s: break; out.append(t)
```

- Offsets are from the shared start moment; a client's next send is its previous **scheduled** time plus the gap, so a
  late send never shifts later ones. No offset beyond `load_time_s`. Each client draws its own gaps from the shared
  `rng` (seeded per step from `secrets.randbits(64)`, recorded in `step-metadata.json`, so a step's schedule can be
  rebuilt).

**`LoadGenerator` (`load/generator.py`):**

```python
class LoadGenerator:
    def __init__(self, driver_cls: type[ClientDriver], endpoint: str, signer: TokenSigner,
                 clients: int, client_timeout_s: float, run_log: RunLog): ...
    async def connect(self) -> None: ...                         # N connect() calls, gathered
    async def run(self, schedule: BurstSchedule | SteadySchedule, test_type: str) -> LoadResult: ...
    def all_settled(self) -> bool: ...                           # every record has a status
    async def close(self) -> None: ...

@dataclass
class LoadResult:
    records: list[RequestRecord]
    t_load_up: datetime                 # first send
    t_load_down: datetime               # steady: t_load_up + load_time_s; burst: last response or timeout
    time_to_answer_all_s: float | None  # burst only
```

- **Clients:** client `i` (1..N) has user `bench-i`, token `signer.token("bench-i")`, its own driver and a session id
  `f"bench-{i}-{uuid4().hex[:12]}"`, new per step. One token per user, one user per client: N clients = N users =
  N tokens.
- **`connect()`** runs before `before` (called by `StepRunner`): `asyncio.gather(..., return_exceptions=True)`; a
  client whose connect failed is kept as failed. It returns when every connect has finished or failed.
- **`run()`**:
  - builds every request up front (`request_id = uuid4().hex`, prompt = the request id, `scheduled_send = start +
    offset`), so request ids are known before they are sent;
  - one sender task per client: `sleep_until(scheduled)` on the monotonic clock, then `driver.send()`; sets `sent` /
    `sent_mono` after the write. A failed client, or a `send()` that raises, marks that request `error` (and, for a
    failed connect, every request of the client);
  - one timeout watcher task: every 0.5 s marks `timeout` any request with `sent_mono + client_timeout_s` passed and
    no status;
  - `on_event` (receive side) fills `first_chunk` / `complete` and status `ok` / `error` for a pending request only;
  - `t_load_up` = the earliest `sent`; burst `t_load_down` = when every request is settled (`run()` awaits that),
    `time_to_answer_all_s` = last settle − first send (monotonic); steady `t_load_down` = `t_load_up + load_time_s`,
    and `run()` returns then, while late replies and timeouts keep updating the records in the background until
    `close()`.
- Connections stay open through the cool-down; `StepRunner` calls `close()` when the step ends.
- Fetcher work never runs on this event loop (see below), so polls can't delay sends.
- **Event-loop load:** 1000 clients = 1000 sockets, ≤ 1000 sender tasks and one receive task each in one process;
  measured health of the load generator is out of scope (#786 Non-goals).

### Step runner (`run/step_runner.py`)

```python
@dataclass
class StepRecord:
    test_type: str; step: int
    started: datetime; before_end: datetime; t_load_up: datetime; t_load_down: datetime; ended: datetime
    cooldown_max_reached: bool
    load: LoadResult
    timed_out: int

class StepRunner:
    def __init__(self, config: BenchConfig, host: Host, invoker: FetcherInvoker, run_log: RunLog): ...
    async def run(self, run: RunInfo, deployment: Deployment, secret: str, test_type: str, step: int,
                  step_dir: Path) -> StepRecord: ...
```

`run()` follows #786 Step timeline with the connect first:

1. `LoadGenerator.connect()` (all N).
2. `started = now`; start one tracking task per `during_step` fetcher (below).
3. Sleep `before_window_s`; `before_end = now`.
4. `StepEndCheck.start(now)`: one plain `fetch()` per `cooldown_checks` fetcher, in a worker thread, kept in memory.
5. `LoadGenerator.run(schedule)` → `t_load_up`, `t_load_down`.
6. Cool-down: loop `StepEndCheck.poll(now)` every `cooldown_poll_interval_s` until it returns a `StepEnd`;
   `ended = StepEnd.at`.
7. Stop tracking: set the stop event; each task does one last `fetch_and_store(last poll, now)` and exits;
   `asyncio.wait(tasks, timeout=30)`; pending tasks are cancelled (their worker thread finishes on its own, its
   result is discarded) and a run-log `WARNING` names the fetcher.
8. `LoadGenerator.close()`.
9. Sleep `after_step_wait_s`; then `fetch_and_store(started, ended)` once per `after_step` fetcher, one after another,
   each in a worker thread through `FetcherInvoker`.
10. If any request timed out: run-log `WARNING "responses for <count> requests were not received within the timeout of <client_timeout_s> s"`.

- **Tracking task** (one per `during_step` fetcher): `last = started`; loop: `now`; `invoker.fetch_and_store(f,
  "during_step", last, now)` via `asyncio.to_thread`; `last = now`; return if stopped; else wait for the stop event
  with timeout `config.fetchers.poll_interval_for(f.name)` (the fetcher's own `poll_interval_s` wins when set). Each
  poll covers (last poll, now), so nothing is fetched twice.
- **Threads:** every `fetch()` / `store()` runs via `asyncio.to_thread` (default executor), so a slow cloud call never
  blocks the event loop that drives the sends and receives. `asyncio.run()` is called once per `step` command.
- The step's CSVs, `summary.csv` row and `step-metadata.json` are written by the `Step` command from the
  `StepRecord` (see Commands), then the lock is released.

**`FetcherInvoker` (`run/fetcher_invoker.py`):**

```python
class FetcherInvoker:
    def __init__(self, run: RunInfo, deployment: Deployment, run_log: RunLog): ...
    def fetch_and_store(self, f: InfoFetcher, list_name: str, start, end, results: Path) -> bool: ...
    def fetch(self, f: InfoFetcher, list_name: str, start, end) -> tuple[bool, Any]: ...
```

- `fetch()` raises the same `FetcherTypeError` when the result is not the family's type, so a cool-down read of the
  wrong type is logged here rather than failing in `has_value()` / `is_settled()`.
- Catches `Exception` (including `FetcherTypeError`), writes run-log `ERROR "fetcher <name> in <list> failed: <type>: <message>"`
  and returns `False`; nothing is stored, so that fetcher's columns stay empty. `KeyboardInterrupt` /
  `CancelledError` are not caught. Shared by `StepRunner`, `StepEndCheck`, `Finish` and `PostRun`.

### Step-end check (`scaling/step_end.py`)

```python
@dataclass(frozen=True)
class StepEnd:
    at: datetime
    max_reached: bool

class StepEndCheck:
    def __init__(self, checks: list[InfoFetcher], invoker: FetcherInvoker, all_settled: Callable[[], bool],
                 lookback_s: float, max_cooldown_s: float): ...
    def start(self, now: datetime) -> None: ...                       # starting values
    def poll(self, now: datetime, t_load_down: datetime) -> StepEnd | None: ...
```

- **`start()`:** per check, `invoker.fetch(f, "cooldown_checks", now - lookback_s, now)`; failure or no value →
  starting value `None` (run-log entry from the invoker or `"<name>: no starting value"`).
- **`poll()`**, in order, stopping at the first check that doesn't hold:
  1. `now - t_load_down >= max_cooldown_s` → `StepEnd(now, max_reached=True)` (checked first, so the maximum ends the
     step even while a check keeps failing);
  2. `all_settled()` (built in);
  3. each check in list order: fetch for `(now - lookback_s, now)`; raises or `not f.has_value(result)` → not met,
     run-log `WARNING`, settle run reset; else `ok = f.is_settled(result, start[f])`.
  4. **Settle window:** per fetcher, `since[f]` = time of the first poll of the current unbroken run of `ok` polls
     (reset to `None` by a failed, empty or not-settled poll). The check holds when `ok` and
     `now - since[f] >= f.settle_window_s` (`settle_window_s = 0` → this poll alone).
  5. all hold → `StepEnd(now, max_reached=False)`.
- Checks later in the list are not fetched in a poll where an earlier one failed, so their settle runs are reset too
  (a run means "held in every poll").
- Runs in a worker thread from `StepRunner` (`asyncio.to_thread(check.poll, ...)`).
- Never changes load or deployment.

### Results

#### Percentiles (`results/percentiles.py`)

```python
PERCENTILES = (0, 25, 50, 75, 99, 100)
def percentiles(values: Sequence[float]) -> dict[str, float | None]: ...
# {"p0": ..., "p100": ...} via numpy.percentile(values, PERCENTILES, method="linear"); all None for an empty input
```

Always over requests (or raw samples), never over per-worker results.

#### Per-request CSV (`results/per_request.py`)

`PerRequestWriter(driver_cls).write(step_dir, records)` reads `stage-timestamps.csv` and writes `per-request.csv`:

- `request_id, session_id, user_id, scheduled_send, sent, first_chunk, complete, latency_s, status`;
- one `<STAGE>_ts` column per request-path stage (every `TraceStage` except `RESPONSE_POLL_START`,
  `RESPONSE_FOUND`);
- one `<STAGE>_s` per request-path stage, then `CLIENT_RECEIVED_s`.

Durations, for the chain `[client sent] + driver_cls.trace_stages + [client complete]`: each stage's duration is
previous point → this point, so `REQUEST_RECEIVED_s` = sent → `REQUEST_RECEIVED`, `AGENT_DONE_s` =
`AGENT_START` → `AGENT_DONE` in complete, and `CLIENT_RECEIVED_s` = `RESPONSE_DELIVERED` → complete. A stage not in
the driver's chain (`AGENT_FIRST_CHUNK_s` for complete) stays empty; a missing point on either side → empty.

#### Per-time-window CSV (`results/per_window.py`)

`WindowGrid(started, ended, time_window_s)`: window `k` covers `[started + k·w, started + (k+1)·w)`, the last window
ends at or after `ended`. Columns:

- `window_start, step_part` (`before` / `load` / `cooldown` by window start against `before_end` and `t_load_down`);
- `tx_per_s, rx_per_s` (sent / `ok`-completed in the window ÷ `w`), `errors, timeouts` (by `settled` time);
- `latency_p0 … latency_p100` over `ok` requests completed in the window;
- per queue × fetcher: `<queue>.waiting.<fetcher>`, `<queue>.in_flight.<fetcher>` (from `queue-depth.csv`);
- per tier × count type × fetcher: `<tier>.<count_type>.<fetcher>` (from `scaling-samples.csv`; `ScalingCollector`);
- per tier × metric × stat × fetcher: for `stat == value` series, `<tier>.<metric>.p0..p100.<fetcher>` over the
  workers' carried values in the window; for `min` / `avg` / `max` series, `<tier>.<metric>.<stat>.<fetcher>`
  (`ResourceCollector`).

**Fill rule** (`design.md`): per series, the last sample with `ts <= window end`, used only if
`window end - ts <= carry`. `carry` = the fetcher's resolved poll interval when it is in `during_step`; otherwise the
series' own sample period, taken as the smallest positive gap between its consecutive samples (one sample → it
fills only the window it falls in). Older → empty cell.

**Empty columns:** columns are laid out from the host and deployment, not from what was stored, so a fetcher that
failed every time still has its (empty) columns: queues from `deployment.queues`; scaling from
`deployment.resources` × `count_types` of every `ScalingInfoFetcher` in the host's step lists; resources from
`deployment.resources` × `metrics` of every `ResourceUsageFetcher` in them. Series found in the files but not
declared are added after the declared ones.

#### Derived scaling numbers (`scaling/derived.py`)

`ScalingDerivation.derive(samples, spans, queue_samples, t_load_up, t_load_down, ended)` per tier × fetcher, from raw
sample times (definitions: `docs/specs/786-benchmark-system/research/platform-scaling-and-cost.md:363-401`):

| Column | Rule (times in seconds from the reference) |
|---|---|
| `decision_delay_s` | first `desired` sample after `t_load_up` greater than `workers_before_up` (desired) − `t_load_up`; empty without `desired` |
| `first_new_worker_s` | first `running` increase after `t_load_up`, or the first span `started` after it, whichever is earlier − `t_load_up` |
| `scale_up_done_s` | first time `running` reaches `workers_peak` − `t_load_up` |
| `scale_down_start_s` | first decrease of `desired` (else `running`) after `t_load_down` − `t_load_down` |
| `scale_down_done_s` | first time after `t_load_down` `running` is back to `workers_before_up` − `t_load_down` |
| `workers_before_up` | latest `running` at or before `t_load_up` |
| `workers_peak` | max `running` in `[started, ended]` |
| `workers_before_down` | latest `running` at or before `t_load_down` |
| `workers_after_down` | latest `running` at or before `ended` |
| `scale_up_rate_per_min` | (`peak − before_up`) ÷ (`scale_up_done_s` / 60); empty when no increase or done time is 0 / empty |
| `scale_down_rate_per_min` | (`before_down − after_down`) ÷ (`scale_down_done_s` / 60); same rule |

- `backlog_drained_s` is per queue × transport fetcher: first time after `t_load_up` the queue's `waiting` is back to
  its latest value at or before `t_load_up` − `t_load_up`, considering only samples after the first one above it.
- No `running` source → every `running`-based column empty. A step that didn't scale: from → to counts filled
  (e.g. 1 → 1), times and rates empty.

#### Summary CSV (`results/summary.py`)

`summary.csv` per test type; `SummaryWriter.upsert(test_type_dir, row)` keyed by `step` (a `KeyedCsv`), so each step
writes or replaces its own row, and `remove(step)` serves `--replace`. Columns:

- `step, started, ended, cooldown_max_reached, requests, ok, errors, timeouts, time_to_answer_all_s` (burst; empty
  for steady);
- `latency_p0 … latency_p100, latency_n`; per stage `<STAGE>_p0 … _p100, <STAGE>_n` (incl. `CLIENT_RECEIVED`);
- `tx_min, tx_avg, tx_max, rx_min, rx_avg, rx_max` over the `load` and `cooldown` windows;
- per tier × fetcher the derived scaling columns (`<tier>.<column>.<fetcher>`); per queue × fetcher
  `backlog_drained_s`;
- per tier × metric × fetcher: `stat == value` series → `p0 … p100` over all raw samples in `[started, ended]`;
  `min` / `avg` / `max` series → the min of `min`, the mean of `avg`, the max of `max` samples.

#### Metadata (`results/metadata.py`)

- `run-metadata.json` (by `Deploy`): run id, deployment id, start time, host, platform, mode, message type, AK
  version (`importlib.metadata.version("agentkernel")`) and git commit (`git rev-parse HEAD`, empty when unavailable),
  agent (`mock` / `real`) and both delays, then every #786 Run metadata field from `deployment.settings`; a field the
  host doesn't give is written as `null`.
- `step-metadata.json` (by `Step`): test type, step, min / max send interval, load time, before window, max cool-down
  (after the host override), after-step wait, cool-down poll interval and lookback, every resolved poll interval by
  fetcher name, client timeout, time window, percentile method (`linear`), the schedule seed, and the step window
  times.

#### Graphs (`results/plots.py`, `cost/report.py`)

```python
class StepPlots:      def draw(self, step_dir: Path, test_type: str, host: Host, deployment: Deployment) -> None: ...
class TestTypePlots:  def draw(self, test_type_dir: Path, step_dirs: list[Path]) -> None: ...
class CostReport:     def draw(self, deployment_dir: Path) -> None: ...      # only when cost.csv exists
```

- Files and content as #786 Graphs: per step `01-stage-times`, `02-stage-breakdown`, `03-timeline`,
  `04-every-request` (steady only), `05-resource-usage`; per test type `01-latency-per-step`,
  `02-stage-times-per-step`, `03-resource-usage-per-step`; billed cost by service. Drawing rules (six percentiles,
  `whis=(0, 100)` boxes with a p99 marker, bands with p50 and dashed p99 lines, one panel per tier / stage / queue, no
  twin axes, no threshold lines) are #786's; `Scratches/25.Benchmarking-Design/graph-examples/plot_examples.py` is the
  layout reference.
- Inputs are only the CSVs (and the host / deployment for panel layout), so `plot` redraws anything at any time.
- A panel with no data is drawn with its axes, title and a "no data" note, never skipped.
- Each PNG is written to a temp name and renamed, so a failed draw never leaves a half file; a draw that raises is a
  run-log `ERROR` naming the graph, and the other graphs still draw.

### Module-level functions

- `percentiles()` (`results/percentiles.py`): stateless numeric helper used by the per-request, per-window, summary,
  resource and plot code; no single owning class.
- `main()` (`cli.py`): the console-script entry point (`[project.scripts]` needs a callable); one line,
  `sys.exit(BenchCli().run(sys.argv[1:]))`.

### Consumer changes

- `.github/workflows/test-reusable.yaml`, job `unit-tests` (`:128-156`): one new step after "Test ak-py":

  ```yaml
  - name: Test benchmark harness
    working-directory: benchmarks
    run: uv run pytest
  ```

  It installs `agentkernel` from the checked-out `ak-py/` path source, so it tests the parser of the branch.
- O8 (app tests in CI) stays open per `design.md`; if decided yes, a second step with
  `working-directory: benchmarks/app`.
- Nothing else in the repo changes. `ak-py` is untouched (the `TRACE` level and parser are #911).

### Config changes

- **`AKConfig`: no changes.**
- New, harness-only file `ak-bench.yaml` (`BenchConfig` above), with exactly the #786 keys plus
  `step_run.cooldown_poll_interval_s` (default 10) and `step_run.cooldown_lookback_s` (default 180), read by
  `StepRunner` / `StepEndCheck`. Nothing existed before, so there is no compatibility concern.
- The app's `config.yaml` uses existing AK keys only; `identity.provider.secret_key` is a bring-your-own provider
  setting read through `model_extra`.

### Behavioural changes

None to Agent Kernel: no file under `ak-py/` changes, and the app uses only public extension points (a `Runner`
subclass, an `IdentityProvider` subclass by dotted path, `AgentReplyAny`).

Departures from house patterns, as `design.md` already records them:

1. Own config file, not `AKConfig` (benchmark settings, not AK runtime config).
2. Host registry and driver factory without a bring-your-own branch (only the AK team runs the benchmark).
3. No deployer class; deployment is the folder's scripts.

**Non-changes:** the AK WebSocket frame, the trace-line format and `TraceLine.parse()` are used as they are.

### Decisions made while detailing

For the reviewer: none changes a `design.md` requirement, but each fills a gap it leaves.

1. **`InfoFetcher.has_value()`** on the two cool-down families, so "returned no value" can be logged without the
   harness reading a result type.
2. **`ResourceUsageFetcher.metrics`** (`(metric, stat)` pairs), parallel to `count_types`, so a resource fetcher that
   failed every time still gets empty columns.
3. **`Fetchers.validate()` also refuses a fetcher without a `name`.**
4. **Carry-forward limit for non-polled series** = the series' smallest sample gap (no new fetcher parameter).
5. **`REQUEST_RECEIVED_s`** = client sent → `REQUEST_RECEIVED` (the chain starts at the client), and the stage chain
   comes from `ClientDriver.trace_stages`.
6. **Reply matching**: frame `request_id` when present, else the connection's in-flight id found in the frame text
   (the complete reply body carries no request id). With the real agent, matching relies on the agent repeating the
   prompt.
7. **`host_settings.<host>` accepts any keys** (they are host-specific and go to `deploy.sh` as JSON); only
   `max_cooldown_s` is typed. Every other block refuses unknown keys.
8. **Run id format** `%Y%m%dT%H%M%SZ`, `--run-id` without `-`, so the deployment id splits unambiguously.
9. **Global CLI flags** `--config`, `--results-dir`, `--deploy-root` (CLI flags, not config keys).
10. **`auth_secret` removed from `state.json`** by a successful `finish`; the file is `0600` until then.
11. **Max cool-down checked first in each poll**, so a check that keeps failing can't hold the step open.

## Error handling

| Failure | Where | What happens |
|---|---|---|
| `ak-bench.yaml` missing / invalid YAML / unknown key / missing required key | `BenchConfig.get()` | `BenchConfigError` naming the key path; exit 1; nothing runs |
| unknown host / no driver for mode × message type | `HostRegistry.get`, `DriverFactory` | `BenchConfigError` naming the built-ins |
| invalid host fetcher lists | `Fetchers.validate` | `HostRefused` naming host and fetcher, before deploy |
| unknown `fetchers.<name>` | `FetchersConfig.check_names` | `BenchConfigError` naming key and known names, before deploy |
| `mock_agent` half set / negative / min > max | `MockAgentConfig.delays` | `BenchConfigError` naming the key, before deploy |
| missing deployment folder or script | `DeploymentFolder.check` | `BenchConfigError` naming the path, before deploy |
| `deploy.sh` exits ≠ 0 or writes no valid `deployment.json` | `Deploy` | run-log `ERROR`, `destroy.sh` runs, `ScriptFailed`, exit 1 |
| `destroy.sh` exits ≠ 0 | `Finish`, `Deploy` cleanup | run-log `ERROR` ("resources may be left running"), exit 1 (in `Deploy` cleanup: logged, original error raised) |
| step lock held (live / other machine) | `StepLock.acquire` | `StepRefused` naming holder and since |
| stale lock (same machine, dead pid) | `StepLock.acquire` | taken over, run-log `WARNING` |
| step folder exists, step not in saved load steps, torn-down deployment | `Step` | `StepRefused`, nothing runs |
| client connect fails | `LoadGenerator.connect` | client's requests `status = error`; step continues |
| `send()` raises | sender task | that request `status = error`; step continues |
| no reply in `client_timeout_s` | timeout watcher | `status = timeout`; end-of-step `WARNING` with the count |
| fetcher raises / wrong type (storing list) | `FetcherInvoker` | run-log `ERROR` (fetcher, list, error); nothing stored; run continues |
| cool-down read raises / no value | `StepEndCheck.poll` | not met, run-log entry, settle run reset; max cool-down ends the step |
| tracking task hangs at stop | `StepRunner` | cancelled after 30 s, run-log `WARNING` |
| graph draw raises | plots | run-log `ERROR` naming the graph; other graphs drawn |
| exception or Ctrl-C during `run` | `Run` | `Finish` runs; second Ctrl-C skips it with a run-log `ERROR`; exit ≠ 0 |
| exception or Ctrl-C during `step` | `Step` | lock released; partial folder kept; no `summary.csv` row |
| `BenchIdentityProvider` without a secret | app startup | `AKConfigError` at build |
| bad token | `BenchIdentityProvider.authenticate` | `AuthenticationError` → AK closes the socket (`pipeline/ws/handler.py:192-212`) |

Missing optional dependencies don't apply: every harness dependency is required, and no cloud SDK is imported.

## Testing

All tests run without a cloud account or network beyond `127.0.0.1`. Async tests use `@pytest.mark.asyncio`
(`ak-dev-testing-conventions`, Async Test Patterns). Run with `cd benchmarks && uv run pytest` (and
`cd benchmarks/app && uv run pytest` for the app).

**Fixtures (`tests/conftest.py`, `tests/mocks/`):**

- `MockWsServer`: `websockets.serve` on `127.0.0.1:0`; checks `token` against a `TokenSigner` secret (closes with
  1008 otherwise); for each chat frame replies `CHAT_QUEUED`, then after `delay_s` a `CHAT_RESPONSE`
  `{"result": "content={'echo': '<prompt>'}", "session_id": ...}` (no request id, like AK); options: `drop` (set of
  request ids never answered), `fail_connect_for` (users refused), `delay_s`; counts frames per user.
- Mock fetchers, one per family plus `RaisingFetcher` and `WrongTypeFetcher`, each with a scripted list of results
  (or exceptions) returned in order, and a call log of `(start, end)` windows.
- `mock_host()`: `during_step=[scaling, transport]`, `cooldown_checks=[transport, scaling]`,
  `after_step=[trace, resource]`, `after_all_steps=[]`, `after_teardown=[cost]`; registered with
  `monkeypatch.setitem(HostRegistry._BUILTINS, "mock", ...)`.
- `tests/mocks/deploy/mock-async-complete/`: `deploy.sh` writes `deployment.json` with
  `endpoint=$MOCK_WS_URL` and fixed `resources` / `queues` / `logs` / `settings`, and records its env to a file;
  `destroy.sh` records that it ran. `MOCK_DEPLOY_EXIT` / `MOCK_DESTROY_EXIT` make either fail.
- `fast_config`: a `BenchConfig` with all waits scaled to tenths of a second (`before_window_s=0.2`,
  `after_step_wait_s=0.1`, `cooldown_poll_interval_s=0.05`, `time_window_s=0.1`, `client_timeout_s=1`, steady
  `load_time_s=0.5`, intervals 0.1–0.2).

**New test files and what they assert (the `design.md` acceptance criteria):**

| File | Asserts |
|---|---|
| `test_config.py` | defaults equal the #786 example; env vars override the file; other `AK_BENCH_` variables ignored; `get()` singleton; `--config` sets the path; unknown top-level key named; missing `step_run.time_window_s` / `fetchers.default` named; unknown key named; `host_settings.x.anything` accepted; `max_cooldown_for` override; `check_names` refuses `aws.ecs-api` listing known names; `mock_agent` table (both / neither / one / negative / min > max) |
| `test_registries.py` | unknown host / driver error lists built-ins; `HostRegistry.get` runs `validate` |
| `test_fetchers_base.py` | `validate` refuses: cooldown fetcher without `is_settled`, scaling without `running`, nameless fetcher (message names host + fetcher); `fetch_and_store` wrong type → `FetcherTypeError` naming fetcher, expected, returned |
| `test_family_store.py` | each family writes its file and columns; a second store with the same key replaces the row (all five families, incl. spans latest-wins); two threads storing 500 rows each into one file lose none |
| `test_is_settled.py` | scaling: equal / higher / missing tier / `start=None`; transport: zero / waiting / in-flight / multiple queues, latest sample wins |
| `test_step_end.py` | order (requests → checks in list order, later not fetched while earlier fails); settle window (holds only after `settle_window_s` of consecutive ok polls); a raising read and an empty read reset the run and log; empty `cooldown_checks` ends once requests settle; max cool-down with host override → `max_reached` |
| `test_schedule.py` | burst: one offset per client; steady: gaps within [min, max], next = previous scheduled + gap, none > `load_time_s`, min = max gives a fixed interval, per-client draws differ |
| `test_load_generator.py` (MockWsServer) | all connects finish before `run()`; burst sends one request per client, all within a few ms; N clients → N distinct users and tokens, one connection each; request ids unique and in the prompt; responses matched without request id in the frame; dropped reply → `timeout` after `client_timeout_s`; refused connect → that client's requests `error`, others `ok`; latency from monotonic clock; a late send doesn't shift later scheduled sends |
| `test_ws_complete_driver.py` | frame shape; token in query; `CHAT_QUEUED` ignored; `SYSTEM_RESPONSE` FAILED and `error`-key replies → `error`; duplicate reply dropped |
| `test_step_runner.py` | connect happens before `before` starts; `during_step` windows are contiguous (last poll, now) and a final poll after stop; a hanging tracker is cancelled after the stop timeout (patched to 0.2 s); `after_step` gets (step start, step end) after the wait; a raising fetcher → empty columns + run-log entry, step completes; the missing-responses `WARNING` text and count |
| `test_state_and_lock.py` | stale lock (dead pid, this host) taken over with log; live lock refused; other-host lock refused; `--force-unlock` prints holder, honours `--yes` / declined prompt, logs; lock released on success, exception and `KeyboardInterrupt` |
| `test_commands.py` (mock folder + MockWsServer) | full deploy → step (steady and burst) → plot → finish → post-run produces every CSV, every graph, `run-metadata.json`, `step-metadata.json`, `cost.csv` and the cost graph; script env contains the contract variables (mock delays only with `mock_agent`); `state.json` round-trips `Deployment` unchanged and loses `auth_secret` after finish; refusals: existing step folder without `--replace` (and `--replace` replaces folder + row), step not in saved load steps, concurrent step, `run --steps 7` before any deploy, unknown `fetchers.<name>` and missing folder before any script; existing host × mode × message type in a run id refused |
| `test_teardown_guarantee.py` | `run` with a step that raises → `destroy.sh` ran and the error surfaces; `KeyboardInterrupt` during a step → `destroy.sh` ran; second interrupt during finish → logged skip; `deploy.sh` failure → `destroy.sh` ran, exit 1; `destroy.sh` failure → run-log `ERROR`, exit 1 |
| `test_results.py` (recorded CSV fixtures) | percentiles match `numpy.percentile(..., method="linear")` and are empty for no data; per-request durations incl. `REQUEST_RECEIVED_s`, `CLIENT_RECEIVED_s`, empty `AGENT_FIRST_CHUNK_s`; per-window Tx / Rx / errors / timeouts / latency; carry-forward limit (poll interval, and sample gap for after-step series); declared-but-empty columns for a fetcher that stored nothing; derived scaling numbers for a scale-up-and-down series, a no-scale series (1 → 1, empty times / rates) and a no-`running` source; summary row replaced on re-run; step folder padding |
| `test_plots.py` | every phase-1 graph file is produced from recorded data, including one with all-empty resource data (panels drawn, not skipped); cost graph only when `cost.csv` exists |
| `test_token_cross_check.py` | a `TokenSigner` token is accepted by `BenchIdentityProvider` (imports the app module by path; the app's dependencies are a subset of the harness's) |
| `app/tests/test_mock_agent.py` | `run()` sleeps within [min, max] (patched `asyncio.sleep` records the delay; `random.uniform` bounds over many draws), echo content, nothing added to the session, variables read once at creation; `agent.py` registers `MockAgent` with both variables, the real agent with neither, and raises with one |
| `app/tests/test_identity.py` | signed token → `Principal(subject="bench-7", kind="user", provider="bench", namespace="bench")`; changed user, changed signature, no `.`, empty user / signature, unsigned token → `AuthenticationError`; missing / empty secret → `AKConfigError` at build; same token for the same user every time (`TokenSigner`) |

- Riskiest consumer: `Run`'s teardown path (a missed `finish` leaves cloud resources running) has its own file.
- No existing test file changes; no AK patch targets move.

## Requirements traceability

| `design.md` section | Spec section |
|---|---|
| Project | Project layout; Dependencies and tooling; Module-level functions |
| Configuration | Configuration |
| Registries | Registries |
| Mock agent app | Mock agent app |
| Client authentication | Client authentication; State (secret lifetime) |
| Load generator and client driver | Load generator and client driver |
| `InfoFetcher` and families | Platform base; Step runner (`FetcherInvoker`) |
| Deployment folders, deployment and hosts | Deployment folders; Platform base (`Deployment`, `Host`) |
| Step runner | Step runner |
| Step-end check | Step-end check |
| Commands and state | Commands; State; Run log |
| Results, derived numbers and graphs | Results |
| Testing | Testing; Consumer changes |
