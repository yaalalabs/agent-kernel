# #786: Benchmark system for throughput, latency, scaling and cost — Implementation Spec

How the approved [`design.md`](design.md) is built. Two parts:

- **AK change (`ak-py`)**: the opt-in pipeline trace logger (`core/pipeline_trace.py`), its config field, and the
  conversion of the existing stage-style INFO lines into trace points on every phase-1 path.
- **Benchmark project (`benchmarks/`)**: a separate uv project with the runner (`ak_bench` package), the benchmarked
  AK app with the mock agent (`app/`), and its tests. Everything platform-specific sits behind ABCs; hosts are bundles
  of small implementations chosen by name.

Every `path:line` below was checked on `develop` at `f11e3b2e` (2026-10-25).

## Design

### 1. Pipeline trace logger (`ak-py/src/agentkernel/core/pipeline_trace.py`)

```python
class TraceStage(str, Enum):
    """Pipeline stages, in request order. The value written to the log is the name."""
    REQUEST_RECEIVED = "REQUEST_RECEIVED"
    INPUT_ENQUEUED = "INPUT_ENQUEUED"
    AGENT_RECEIVED = "AGENT_RECEIVED"
    AGENT_START = "AGENT_START"
    AGENT_FIRST_CHUNK = "AGENT_FIRST_CHUNK"
    AGENT_DONE = "AGENT_DONE"
    OUTPUT_ENQUEUED = "OUTPUT_ENQUEUED"
    OUTPUT_RECEIVED = "OUTPUT_RECEIVED"
    RESPONSE_DELIVERED = "RESPONSE_DELIVERED"
    RESPONSE_POLL_START = "RESPONSE_POLL_START"  # rest_sync only
    RESPONSE_FOUND = "RESPONSE_FOUND"            # rest_sync only


class PipelineTraceRecord(BaseModel):
    """One parsed trace line."""
    ts: datetime          # timezone-aware UTC
    stage: TraceStage
    request_id: str
    message: str | None = None


class PipelineTraceFormatter(logging.Formatter):
    """Formats a trace LogRecord as the fixed AK_TRACE line."""
    MARKER = "AK_TRACE"
    def format(self, record: logging.LogRecord) -> str: ...


class PipelineTraceParser:
    """Turns raw log text back into PipelineTraceRecords. Lives next to the formatter so both change together."""
    @classmethod
    def parse_line(cls, line: str) -> PipelineTraceRecord | None: ...   # None for any non-trace line
    @classmethod
    def parse_lines(cls, lines: Iterable[str]) -> Iterator[PipelineTraceRecord]: ...


class PipelineTrace:
    """Process-wide switch and the one call an AK developer writes per trace point."""
    LOGGER_NAME = "ak.pipeline_trace"
    _enabled: ClassVar[bool] = False

    @classmethod
    def configure(cls, enabled: bool) -> None: ...
    @classmethod
    def is_enabled(cls) -> bool: ...
    @classmethod
    def log(cls, stage: TraceStage, request_id: str | None, message: str | None = None) -> None: ...
```

Rules:

1. **Line format.** `PipelineTraceFormatter.format` returns
   `<ts> AK_TRACE stage=<STAGE> request_id=<id>[ message="<text>"]`.
   - `<ts>` = `datetime.fromtimestamp(record.created, timezone.utc)` printed as `%Y-%m-%dT%H:%M:%S.%fZ` (UTC,
     microseconds). The default `asctime` is local time with millisecond precision, which is too coarse for
     sub-millisecond stages.
   - `message` is omitted when `None` or empty. Inside it, `\` and `"` are escaped as `\\` and `\"`, and newlines as
     `\n`, so one record is always one line.
   - The stage and request id are passed in `record.args`/`extra` (not interpolated by the caller), so the formatter
     owns the layout.
2. **Parser.** `parse_line` finds the `AK_TRACE` marker anywhere in the line, so a prefix added by a log backend
   (CloudWatch's own timestamp, a container runtime prefix, `kubectl logs --timestamps`) is ignored. It reads the
   timestamp token immediately before the marker. An unknown stage name or a malformed line returns `None`; it never
   raises. `parse_lines` skips `None`s.
3. **Off by default, cheap when off.** `log` checks `_enabled` first and returns at once: no string formatting, no
   `LogRecord`. Callers must not build message strings before the call; when a message needs formatting, the call
   site wraps it in `if PipelineTrace.is_enabled():`. Only the `AGENT_DONE`/`OUTPUT_ENQUEUED` sites with a status code
   do this.
4. **On.** `configure(True)` sets `_enabled`, and sets up `logging.getLogger("ak.pipeline_trace")`: level `INFO`,
   `propagate = False`, its handlers replaced by one `StreamHandler` with `PipelineTraceFormatter`. An explicit level
   is required: the parent `ak` logger is set to `logging.ak.level` (`core/logger.py:59-69`), so an unset child level
   would inherit e.g. `WARNING` and drop every trace line. `configure(False)` clears `_enabled` and removes the
   handlers. `configure` is idempotent.
5. **`request_id` missing.** `log` with a falsy `request_id` writes nothing (the parser could not join it). Every
   phase-1 site has one.
6. **Not exported** from `agentkernel` or `agentkernel.core`'s `__all__` beyond `from agentkernel.core.pipeline_trace
   import ...`. It is internal tooling, not a user feature, and the module imports only the standard library and
   pydantic.
7. **No AKConfig reads in the module.** `AKLogger` passes the flag in (rule of section 2), so the module is safe to
   import from the benchmark project without loading a `config.yaml`.

### 2. Config and logger wiring

`core/config.py`, before `_LoggingConfig` (`:663-665`):

```python
class _PipelineTraceConfig(BaseModel):
    enabled: bool = Field(
        default=False,
        description=(
            "Write one AK_TRACE log line per pipeline stage per request (request received, enqueued, agent start/done, "
            "output enqueued, response delivered) on a dedicated logger. For benchmarks and latency debugging; "
            "adds log volume on every request, so keep it off in normal use."
        ),
    )


class _LoggingConfig(BaseModel):
    ak: ...      # unchanged
    system: ...  # unchanged
    pipeline_trace: _PipelineTraceConfig = Field(
        description="Pipeline stage trace logging", default_factory=_PipelineTraceConfig
    )
```

`core/logger.py` `AKLogger.configure_from_config` (`:85-98`): after the `ak`/`system` levels, call
`PipelineTrace.configure(config.logging.pipeline_trace.enabled)` (import at module top; `pipeline_trace` imports
nothing from `core`, so there is no cycle). It runs once per process on the first `AKConfig.get()`
(`core/config.py:1089-1095`), in every process type (IO handler, agent runner, gateway, each Lambda).

- Env var: `AK_LOGGING__PIPELINE_TRACE__ENABLED=true`. The benchmark deployers set it this way, so the app's committed
  `config.yaml` stays benchmark-neutral.
- Why not reuse `_LogLevelConfig` (`level`): a level for a logger that only ever writes at INFO is a disguised on/off
  switch, and `level: DEBUG` would read as "more detail" when it means nothing more.

### 3. Trace points

The replaced lines and the new points, per file. "Replace" removes the `self._log.info(...)` line and puts the trace
call at the stage's exact point; anything the old line carried that the trace needs goes into `message`.

| File | Today | Change |
|---|---|---|
| `pipeline/request_handler.py:136` | `[REQUEST START]` | `REQUEST_RECEIVED` |
| `pipeline/request_handler.py:141` | `[ENQUEUED]` | `INPUT_ENQUEUED` |
| `pipeline/request_handler.py:146` | `[WAITING]` | `RESPONSE_POLL_START` |
| `pipeline/request_handler.py:160` | `[RESPONSE FOUND]` | `RESPONSE_FOUND` |
| `pipeline/request_handler.py:318` | `[STREAM REQUEST]` | `REQUEST_RECEIVED` |
| `pipeline/ws/handler.py:228-246` | `[ENQUEUED]` at `:246` | new `REQUEST_RECEIVED` after `request_id` is resolved (`:228`), `INPUT_ENQUEUED` replaces `:246` |
| `integration/adapter/producer.py:90` | `[ENQUEUED]` | `INPUT_ENQUEUED`, `message=f"integration={adapter_name}"` |
| `pipeline/agent_runner.py` (`AgentRunner`) | `[AGENT START]` `:49`, `[AGENT DONE]` `:57` (after the output send) | new `AGENT_RECEIVED` at entry of message handling; `AGENT_START` replaces `:49`; `AGENT_DONE` moves to right after `ChatService` returns, before the output send; new `OUTPUT_ENQUEUED` after the send returns |
| `pipeline/agent_runner.py` (`StreamAgentRunner`) | `[STREAM AGENT START]` `:226`, `[STREAM AGENT DONE]` `:244` | same stages; new `AGENT_FIRST_CHUNK` on the first chunk; `OUTPUT_ENQUEUED` after the last chunk's send; `[REALTIME CHUNK]` `:274` kept (debug) |
| `pipeline/response_handler.py` | `[OUTPUT DONE]` `:231`, `:262` | new `OUTPUT_RECEIVED` at entry of message handling; `RESPONSE_DELIVERED` replaces `:231` and `:262` (for `STREAM_CHUNK`, only on the final chunk); chunk debug line `:206` kept |
| `pipeline/integration_delivery.py:104` | `[OUTPUT DONE]` | `RESPONSE_DELIVERED`, `message=f"integration={integration}"` |
| `deployment/aws/containerized/core/api/websocket_api.py:335-351` | "Enqueuing WS chat request" (untagged) | new `REQUEST_RECEIVED` at the start of `_enqueue_chat`, new `INPUT_ENQUEUED` after `send_message_to_input_queue` returns; the existing line is kept as is (not a stage line) |
| `deployment/aws/containerized/akagentrunner.py` | `[AGENT START]` `:135` (dequeue), `[AGENT PROCESSING]` `:141`, `[AGENT RESPONSE]` `:148`, `[AGENT DONE] Sent to output queue` `:154`; stream `:246`, `:262` | `AGENT_RECEIVED`, `AGENT_START`, `AGENT_DONE`, `OUTPUT_ENQUEUED` respectively; stream: `AGENT_RECEIVED` (`:246`), `AGENT_START`, `AGENT_FIRST_CHUNK`, `AGENT_DONE`, `OUTPUT_ENQUEUED` (`:262`); `[REALTIME CHUNK]` `:332` kept |
| `deployment/aws/containerized/akoutputconsumer.py` | `[OUTPUT START]` `:63`, `[OUTPUT DONE]` `:74`, `:83` | `OUTPUT_RECEIVED`, `RESPONSE_DELIVERED`, `RESPONSE_DELIVERED`; `[OUTPUT STORE]` `:79` kept |
| `deployment/aws/serverless/core/router/ws_lambda.py:367-410` (`_handle_queue_mode`) | untagged | new `REQUEST_RECEIVED` after the `request_id` check (`:386-387`), new `INPUT_ENQUEUED` after the queue send |
| `deployment/aws/serverless/akagentrunner.py` | untagged (`:105`, `:129`) | `process_message` (`:169`): new `AGENT_RECEIVED`, `AGENT_START`, `AGENT_DONE`; the send helper (`:148`): new `OUTPUT_ENQUEUED`; stream runner (`:321`, `:333`): same plus `AGENT_FIRST_CHUNK` |
| `deployment/aws/serverless/akresponsehandler.py` | untagged (`:125`, `:161`) | `process_message` (`:128`): new `OUTPUT_RECEIVED`; new `RESPONSE_DELIVERED` after the broadcast (`:155`, `:157` final chunk only) and after the store write (`:161`); the existing untagged lines are kept |

- The `request_id` at each site comes from what the site already holds (message attributes, the parsed request, the
  record attributes). Where an old line carried only a user id or an SQS message id (`response_handler.py:262`,
  `akoutputconsumer.py:74`), the trace reads `request_id` from the message attributes, where it is already present.
- Not traced in phase 1: the serverless REST request handler (`rest_lambda.py`) and the ECS REST path's Lambda
  equivalents beyond the shared `request_handler.py` lines above. They are added with the REST drivers.
- Dev skills and docs that describe the converted lines: none (`grep` over `ak-py/tests`, `docs/docs`, `.agents`,
  `examples`, `ak-deployment` for the tagged strings returned nothing on 2026-10-25).

### 4. Benchmark project layout (`benchmarks/`)

```
benchmarks/
  README.md                 how to set up accounts/clusters, configure, run, read results
  pyproject.toml            uv project "ak-bench"; agentkernel as a path dependency (../ak-py, extras: aws, api);
                            boto3, kubernetes, websockets, pandas, matplotlib, pydantic, pyyaml; [project.scripts] ak-bench
  bench.example.yaml        documented BenchConfig
  app/                      the benchmarked AK app (one image for every host)
    mock_agent.py           MockAgentPreHook
    auth.py                 BenchTokenValidator(AuthValidator)
    agent.py                the agent definition + hook registration (shared by every entry point)
    app_io.py, app_agent_runner.py, app_lambda_*.py   per-host entry points, following the existing examples
    config.yaml             execution.mode: async; queues from env; no pipeline_trace (set by env)
    Dockerfile
    deploy/                 terraform roots for ecs/lambda (module sources = ../../../ak-deployment/ak-aws/...),
                            helm values for eks/baremetal
  ak_bench/
    cli.py                  BenchCLI
    config.py               BenchConfig and sub-models
    model.py                Run, StepSpec, StepParts, RequestRecord, ResponseEvent, ClientIdentity
    orchestrator.py         RunOrchestrator, HostModeRun
    load/
      generator.py          LoadGenerator (clients, timing, timeouts)
      steps.py              StepRunner (before → load → cool-down), BurstLoad, SteadyLoad, ScalingLoad
      tokens.py             BenchTokenIssuer (per-client tokens)
    drivers/
      base.py               ClientDriver ABC, ClientDriverFactory
      ws_complete.py        WsCompleteDriver
    platforms/
      base.py               Endpoint, Deployment, Deployer, ScalingInfoFetcher, ScalingInfo, CountSample, WorkerSpan,
                            TraceCollector, TransportCollector, QueueDepth, UsageSource, UsageItem, BillingReader,
                            CostItem, PriceSource, PriceTable, Host
      local/                deployer.py (NoopDeployer), log_file_traces.py (LogFileTraceCollector)
      aws/                  session.py (AwsSessionProvider), terraform_deployer.py, ecs_api_scaling.py,
                            ecs_scaling_activities_scaling.py, cloudwatch_metric_scaling.py,
                            lambda_log_streams_scaling.py, cloudwatch_logs.py (CloudWatchLogsQuery),
                            cloudwatch_logs_traces.py, fargate_usage.py, lambda_usage.py, sqs_usage.py,
                            apigw_ws_usage.py, alb_usage.py, eks_control_plane_usage.py,
                            cost_explorer_billing.py, price_list.py
      k8s/                  helm_deployer.py, api_scaling.py, pod_log_traces.py, node_usage.py
      baremetal/            config_prices.py (ConfigPriceSource)
    transports/             sqs.py (SqsTransportCollector), kafka.py (KafkaTransportCollector)
    scaling/                collector.py (ScalingCollector), windows.py (WindowBuilder), derived.py
                            (ScalingDeriver), step_end.py (StepEndCheck)
    cost/                   estimate.py (CostEstimator), model.py (CostModelBuilder), compare.py (BillComparer)
    results/                layout.py (ResultsLayout), writers.py (RequestsCsv, WindowsCsv, SummaryCsv, CostCsv,
                            MetadataWriter), traces.py (TraceJoiner), summary.py (SummaryBuilder)
    plots/                  plotter.py (Plotter), per_run.py, comparison.py
    hosts.py                HostRegistry and the built-in bundles
    sla/                    phase 2: percentiles.py, checker.py (SlaChecker), report.py
  tests/                    pytest suite (section "Testing")
```

- One file per implementation, not one file per interface per host. A new host is a few lines in `hosts.py`.
- Module-level functions: none outside `cli.py`'s `main()` that only does `BenchCLI().run(sys.argv[1:])` (required by
  `[project.scripts]`).

### 5. Configuration (`ak_bench/config.py`)

```python
class LoadConfig(BaseModel):
    steps: list[int] = [1, 10, 100, 1000]
    test_types: list[Literal["burst", "steady", "scaling"]] = ["burst", "steady"]
    steady_duration_s: float            # Q3, no default until decided: required when "steady" is selected
    before_s: float                     # Q3
    max_cooldown_s: float = 2700        # 45 min
    request_timeout_s: float = 120
    window_s: float = 1
    poll_interval_s: float = 5
    sqs_settle_s: float = 60
    scaling: ScalingTestConfig | None = None   # low/high/low levels and hold times; required for "scaling"

class HostConfig(BaseModel):
    type: str                                  # built-in host name or dotted path to a HostFactory
    modes: list[str] = ["ws_complete"]
    region: str | None = None
    deploy: dict[str, Any] = {}                # passed to the deployer as-is (tfvars / helm values overrides)
    fetchers: list[str] | None = None          # order / subset of the host's fetchers; None = host default
    max_cooldown_s: float | None = None        # per-host override
    after_run_wait_s: float = 300              # Q7
    trace_log_file: Path | None = None         # local host only
    endpoint: EndpointConfig | None = None     # local host / --skip-deploy

class CostConfig(BaseModel):
    baremetal_node_hour_usd: float | None = None
    price_overrides: dict[str, float] = {}     # "<service>/<usage type>" -> USD, recorded in price_table.json

class AgentConfig(BaseModel):
    delay_ms: int = 0
    batch_size: int | None = None              # lambda ESM batch size override

class BenchConfig(BaseModel):
    run_id: str | None = None                  # default: UTC timestamp + short random suffix
    results_dir: Path = Path("results")
    hosts: dict[str, HostConfig]
    load: LoadConfig
    agent: AgentConfig = AgentConfig()
    cost: CostConfig = CostConfig()
    token_secret_env: str = "AK_BENCH_TOKEN_SECRET"
```

- Loaded from `--config` (default `bench.yaml`), then CLI overrides applied (`--steps`, `--host`, `--mode`,
  `--test-type`). The resolved config is written to `metadata.json`.
- `steady` selected without `steady_duration_s`, or `scaling` without `load.scaling`, is a `BenchConfigError` before
  anything is deployed.

### 6. Core data types and ABCs (`platforms/base.py`, `drivers/base.py`)

```python
@dataclass(frozen=True)
class Endpoint:
    url: str                       # ws(s):// URL of the chat socket
    auth: dict[str, str]           # e.g. {"query_param": "token"}; how the driver attaches the per-client token

@dataclass(frozen=True)
class Deployment:
    endpoint: Endpoint
    resources: dict[str, dict[str, str]]   # tier -> resource ids, e.g. {"runner": {"cluster": ..., "service": ...}}
    log_targets: dict[str, str]            # tier -> log group / namespace+selector, read by the TraceCollector
    queues: dict[str, str]                 # "input"/"output" -> queue URL or topic (+ "group" for kafka)

class Deployer(ABC):
    @abstractmethod
    def deploy(self, run: Run) -> Deployment: ...
    @abstractmethod
    def teardown(self, run: Run) -> None: ...
    @abstractmethod
    def deployed_settings(self) -> dict[str, Any]: ...   # autoscaling, worker size, batch size, timeouts, partitions

class ScalingInfoFetcher(ABC):
    name: str
    live: bool
    @abstractmethod
    def fetch(self, run: Run, deployment: Deployment, start: datetime, end: datetime) -> ScalingInfo: ...

class TraceCollector(ABC):
    @abstractmethod
    def fetch_lines(self, run: Run, deployment: Deployment, start: datetime, end: datetime) -> Iterator[str]: ...
    def stage_timestamps(self, run, deployment, start, end) -> dict[str, dict[TraceStage, datetime]]:
        """Concrete: parses fetch_lines() with PipelineTraceParser. The earliest timestamp wins per (request, stage)."""

class TransportCollector(ABC):
    @abstractmethod
    def poll(self, deployment: Deployment) -> dict[str, QueueDepth]: ...   # "input"/"output" -> (waiting, in_flight)

class UsageSource(ABC):
    component: str                                   # "compute.fargate", "queue.sqs", ...
    @abstractmethod
    def usage(self, run: Run, deployment: Deployment, start: datetime, end: datetime,
              scaling: ScalingRecord) -> list[UsageItem]: ...           # may read recorded worker spans

class BillingReader(ABC):
    @abstractmethod
    def billed(self, run: Run) -> list[CostItem] | None: ...

class PriceSource(ABC):
    @abstractmethod
    def prices(self, region: str | None, components: list[str]) -> PriceTable: ...

@dataclass
class Host:
    name: str
    deployer: Deployer
    scaling_fetchers: list[ScalingInfoFetcher]
    trace_collector: TraceCollector | None
    transport_collector: TransportCollector | None
    usage_sources: list[UsageSource]
    billing: BillingReader | None
    prices: PriceSource | None
```

```python
class ResponseEventKind(str, Enum):
    FIRST_CHUNK = "first_chunk"
    COMPLETE = "complete"
    ERROR = "error"

@dataclass(frozen=True)
class ResponseEvent:
    kind: ResponseEventKind
    request_id: str
    ts: datetime                # client clock, taken when the frame is read
    detail: str | None = None

class ClientDriver(ABC):
    """One instance per client. Owns one connection."""
    mode: ClassVar[str]
    @abstractmethod
    async def connect(self, endpoint: Endpoint, identity: ClientIdentity) -> None: ...
    @abstractmethod
    async def send(self, request: OutgoingRequest) -> datetime: ...    # returns the client send timestamp
    @abstractmethod
    def events(self) -> AsyncIterator[ResponseEvent]: ...
    @abstractmethod
    async def close(self) -> None: ...

class ClientDriverFactory:
    BUILTIN = ["ws_complete"]
    @classmethod
    def create(cls, mode: str) -> ClientDriver: ...   # if/elif built-ins, else resolve_dotted(mode, base=ClientDriver)
```

- `ClientDriverFactory` and `HostRegistry` reuse `agentkernel.core.util.factory.resolve_dotted` and raise
  `BenchConfigError` naming the built-ins for an unknown short name.
- A fetcher, collector or source that raises is caught by its caller (`ScalingCollector`, `RunOrchestrator`), logged
  to `run.log` with the component name, and treated as "no data". No retries beyond what the SDK client does.

### 7. `WsCompleteDriver` (`drivers/ws_complete.py`)

- `connect`: opens the socket with `websockets` at `endpoint.url`, attaching `identity.token` as `endpoint.auth`
  says (query parameter for the pipeline gateway and API Gateway, as the existing clients do).
- `send`: one chat frame with `request_id`, `session_id`, and `prompt = f"bench:{request_id}"`; returns the timestamp
  taken right before the write.
- `events`: reads frames. `CHAT_QUEUED` acks are ignored. A `CHAT_RESPONSE` frame yields `FIRST_CHUNK` then
  `COMPLETE` with the same timestamp, `request_id` taken from the echoed prompt (`content.echo`). An error frame yields
  `ERROR`. A frame that can't be matched to a request is counted in `run.log` and dropped.
- The exact frame shapes are taken from the existing WS clients in `examples/` for each host while building iteration
  2. All three push paths use the `MessageType` values of `WebSocketHandlerABC` (`CHAT_QUEUED`, `CHAT_RESPONSE`,
  `STREAM_CHUNK`); whether the envelopes are byte-identical across the pipeline gateway, ECS and Lambda is checked
  then. If they differ, the driver gets one small parser per envelope, chosen from `Endpoint`, not per host.

### 8. Load generation (`load/`)

- `LoadGenerator` owns N `ClientSlot`s (driver, identity, session id, in-flight map), connects all N before the step's
  `before` part ends, and closes them after the cool-down.
  - Connection setup time is not part of request latency; connect failures are recorded as `status = error` rows with
    `sent` empty and `detail = "connect"`.
  - Each slot's reader task consumes `events()` and fills the `RequestRecord`s; a per-request timer marks
    `status = timeout` at `request_timeout_s` and stops waiting for it. A late response after a timeout is recorded
    in `run.log` and does not change the row.
- `BenchTokenIssuer` issues one HMAC-signed token per client with a unique `userId` claim (`bench-<run>-<n>`), signed
  with the secret from `token_secret_env`. `BenchTokenValidator` in the app verifies it and returns the claim. The
  secret reaches the app through the deployer's env injection.
- `BurstLoad`: all N slots send one request at a shared start instant (an `asyncio.Event`), then wait for all to
  settle.
- `SteadyLoad`: each slot loops send → wait for complete/error/timeout → send until `steady_duration_s` from the first
  send; then stops sending.
- `ScalingLoad`: runs `low` clients steady for the baseline hold, adds clients up to `high` at `t_load_up` for the
  scale-up hold, removes clients back to `low` at `t_load_down` for the scale-down hold. The three phase boundaries are
  recorded.
- `StepRunner.run(step)`: `before` (sleep `before_s`, recording windows) → `load` → `cool-down` (poll every
  `poll_interval_s` with `StepEndCheck` until it returns a `StepEnd`). Records the start and end of each part.
- Windows: a `WindowRecorder` bucketing client events by `window_s` into Tx/Rx/errors/timeouts/avg latency, and the
  latest `TransportCollector.poll()` result per window (polled every `poll_interval_s`; windows between polls are
  left empty, not interpolated).

### 9. Scaling (`scaling/`)

- `ScalingCollector(fetchers, poll_interval_s)`:
  - `poll_during_run(run, deployment, stop)`: calls each `live` fetcher via `asyncio.to_thread` every poll, with
    (last poll, now), and keeps every result.
  - `latest_running(primary, deployment)`: for `StepEndCheck`, calls the primary fetcher's `fetch` for the last few
    minutes even when it is not `live`; these results are not kept.
  - `collect_after_run(run, deployment)`: calls each non-live fetcher once with (run start, run end), after
    `after_run_wait_s`. Re-run by `collect-scaling`.
  - Spans from several polls are merged by `(tier, worker)`; the latest poll wins.
- `WindowBuilder.to_columns(results, window_s)`: one column per `tier.count_type.fetcher` (e.g.
  `runner.running.aws.ecs_api`). Samples go to the window containing their timestamp (the last sample in a window
  wins); spans are converted to a running count per window (a worker counts in every window it overlaps). Windows
  with no sample stay empty.
- `StepEndCheck(primary, transport, max_cooldown_s, sqs_settle_s)`:
  - `is_over(step, now) -> StepEnd | None`, `StepEnd(at, max_reached)`.
  - condition 1: `step.all_settled()`; condition 2: `transport.poll()` returns `waiting == in_flight == 0` on both
    queues, skipping SQS polls taken less than `sqs_settle_s` after the step's last send; condition 3: the primary
    fetcher's latest running count per tier equals `step.starting_counts` (its counts at the end of `before`). A
    missing source makes that condition true.
  - Lambda idle minutes: a missing `ConcurrentExecutions` datapoint is read as 0 only for minutes older than a
    configured `metric_delay_s` (default 180 s until Q6 is measured).
- `ScalingDeriver.derive(windows, step) -> dict[str, ScalingNumbers]` per `tier.fetcher`: the times and counts listed
  in design.md, from the merged columns. Rules:
  - "first increase" / "first decrease" compare against the count at `t_load_up` / `t_load_down`;
  - "scale-up done" is the first time the running count reaches its maximum in the load + cool-down part;
  - "scale-down done" is the first time running is back at `workers_before_up` after `t_load_down`; empty if never;
  - "backlog drained" is the first window after `t_load_up` whose input-queue waiting count is ≤ its value at
    `t_load_up`;
  - "latency recovered" uses the configured rule (Q4) over windowed avg latency;
  - rates are `change ÷ (end − start)` in workers per minute; empty when either end is empty or the span is 0.

### 10. Traces (`results/traces.py`)

- `TraceJoiner.join(requests, stage_timestamps)` adds one column per `TraceStage` to each request row (empty when
  the stage was not seen), plus the derived durations: `rh_ms` (REQUEST_RECEIVED → INPUT_ENQUEUED), `inq_wait_ms`
  (INPUT_ENQUEUED → AGENT_RECEIVED), `pickup_ms` (AGENT_RECEIVED → AGENT_START), `agent_ms` (AGENT_START → AGENT_DONE),
  `out_send_ms` (AGENT_DONE → OUTPUT_ENQUEUED), `outq_wait_ms` (OUTPUT_ENQUEUED → OUTPUT_RECEIVED), `resp_ms`
  (OUTPUT_RECEIVED → RESPONSE_DELIVERED), `push_ms` (RESPONSE_DELIVERED → client complete), and `client_to_rh_ms`
  (client sent → REQUEST_RECEIVED). The last two mix clocks (see `research/reading-the-results.md`).
- A redelivered message logs a stage twice; the earliest timestamp is kept (rule in `TraceCollector`), and the count
  of duplicates is written to `run.log`.
- Collectors:
  - `LogFileTraceCollector` (`local`): reads `trace_log_file`.
  - `CloudWatchLogsTraceCollector` (`ecs`, `lambda`, and `eks` if Q8 picks Container Insights): one Logs Insights
    query per log group in `deployment.log_targets`, `filter @message like "AK_TRACE"`, paged; uses the shared
    `CloudWatchLogsQuery` helper (also used by `LambdaLogStreamsScalingInfoFetcher` and `LambdaUsageSource`).
  - `PodLogTraceCollector` (`baremetal`, `eks` otherwise): reads every pod's logs for the tier selectors during the
    run window via the K8s API, including pods that already stopped. Pods deleted by scale-in lose their logs, so this
    collector **also streams logs live** (one follow stream per pod, opened as pods appear in the `k8s.api` fetcher's
    spans) and writes them to `results/.../pod_logs/`. `fetch_lines` reads those files.

### 11. Cost (`cost/`)

- `UsageItem(component, unit, quantity, start, end, detail)`; `PriceTable(region, fetched_at, prices: dict[(component,
  unit), usd], overrides)`; `CostItem(component, usd)`.
- `CostEstimator.estimate(usage, prices, window) -> list[CostItem]`: for each item, the share that overlaps `window`
  (pro-rata by time) × unit price. Used for each step (first send → end of cool-down), the before part (idle), and
  the whole run.
- Per step: totals by component, requests by status, `cost_per_1m_ok = total ÷ ok × 1e6` (empty when `ok == 0`), and
  for `steady` the load-part cost × 3600 ÷ load seconds.
- `CostModelBuilder`: `idle_cost_per_hour` from the before parts (average over steps), and `cost_per_1m_messages` per
  component from the largest steady step's usage ÷ its ok requests (the step closest to saturation). Records the agent
  delay with the numbers.
- `BillComparer`: estimated vs billed for the whole run, per component where the billing groups map, else total only.
- Usage sources:
  - `FargateUsageSource`: vCPU-s and GB-s from the `aws.ecs_api` worker spans (`pull_started` → `stopped`, at least
    60 s per task) × the task size from `deployed_settings()`.
  - `LambdaUsageSource`: GB-s and request counts from `REPORT` lines per function (Logs Insights).
  - `SqsUsageSource`: API request counts from CloudWatch `AWS/SQS` metrics per queue
    (`NumberOfMessagesSent`, `NumberOfMessagesReceived`, `NumberOfMessagesDeleted`, `NumberOfEmptyReceives`), with
    sent/received/deleted divided by the configured batch sizes (an estimate, as `research/` explains). Rounded up per
    batch.
  - `ApiGatewayWsUsageSource`: `MessageCount` and `ConnectCount` metrics plus connection minutes from the client's own
    connect/close times.
  - `AlbUsageSource`, `EksControlPlaneUsageSource`: hours the resource existed in the window (plus ALB LCU-hours from
    `ConsumedLCUs`).
  - `K8sNodeUsageSource`: node-hours per instance type from the K8s API node list polled during the run.
- `AwsPriceListPriceSource`: `pricing:GetProducts` (us-east-1 endpoint) for the components the host's usage sources
  declare, on-demand terms only, region-filtered; overrides applied and recorded.
- `ConfigPriceSource`: `$/node-hour` from `cost.baremetal_node_hour_usd`; a `baremetal` run without it records no
  estimate and says so in `run.log`.
- `CostExplorerBillingReader`: `GetCostAndUsage` filtered by tag `ak-bench-run-id = <run>`, daily, grouped by
  `SERVICE`, over the run's dates; only from `collect-cost`.

### 12. Deployers

- `TerraformDeployer(root)`: runs `terraform init/apply -auto-approve` in a per-run working copy of
  `benchmarks/app/deploy/<host>/` with a generated `bench.auto.tfvars.json` (the config's `deploy` block merged over
  the host defaults below, plus `tags = {"ak-bench-run-id": run_id}` and the env vars
  `AK_LOGGING__PIPELINE_TRACE__ENABLED=true`, `AK_BENCH_AGENT_DELAY_MS`, the token secret); reads `terraform output
  -json` into `Deployment`; `teardown` runs `terraform destroy -auto-approve`. State is local to the run folder.
  - `ecs` defaults: `scaling_config = {enabled = true, min_count = 1, ...module defaults}`, `execution_mode =
    "async"`, `queue_mode = true`.
  - `lambda` defaults: `queue_mode = true`, `execution_mode = "async"`; `deploy()` raises `BenchConfigError` when
    `batch_size × delay_ms / 1000 >= agent_runner.timeout` (default 45 s, `ak-aws/serverless/variables.tf:376-381`).
  - The Terraform outputs the deployer needs (WS URL, cluster/service names, function names, queue URLs, log
    groups) are read from each module's existing `outputs.tf`; any missing one is added to the benchmark root's own
    `outputs.tf`, not to the published modules.
- `HelmDeployer(values_file)`: `helm upgrade --install` of `ak-deployment/ak-k8s/chart` into a run namespace with
  `keda.enabled: true`, `transport.type: kafka`, the env vars above via `extraEnv`, and a `ak-bench-run-id` label;
  `teardown` uninstalls and deletes the namespace. The cluster itself is pre-existing (Q8).
- `NoopDeployer` (`local`): returns the `Deployment` from `HostConfig.endpoint`; teardown does nothing.
- Running `terraform`/`helm` is the benchmark user's action against their own account; the CLI prints the target
  account/cluster and asks for confirmation unless `--yes` is passed.

### 13. Orchestration (`orchestrator.py`, `cli.py`)

- `BenchCLI.run(argv)`: parses `run | plot | collect-scaling | collect-cost | sla-check`, loads `BenchConfig`, builds
  a `RunOrchestrator`.
- `RunOrchestrator.run()`: for each selected host × mode, a `HostModeRun`:
  1. `ResultsLayout` creates `results/<run-id>/<host>/<mode>/`; `run.log` handler attached.
  2. `deployer.deploy()` unless `--skip-deploy`; `metadata.json` written with `deployed_settings()`.
  3. `prices.prices(...)` → `price_table.json`.
  4. `ScalingCollector.poll_during_run` started as a task; pod log streaming started when the host has a
     `PodLogTraceCollector`.
  5. For each test type, for each step: `StepRunner.run(step)`.
  6. Stop polling; wait `after_run_wait_s`; `collect_after_run`; `trace_collector.stage_timestamps`; usage from each
     source → `usage.json`.
  7. Write `requests.csv`, `windows.csv`, `summary.csv`, `cost.csv`; `Plotter.per_run`.
  8. `deployer.teardown()` unless `--skip-teardown` (in a `finally`, so a failure in 3-7 still tears down).
- After all pairs: `Plotter.comparison(run_id)`.
- `plot`, `collect-scaling`, `collect-cost` reuse the same writers and plotter from the saved files; `collect-scaling`
  needs the deployment's resource ids, which are saved in `metadata.json`.

### 14. Mock agent and app (`benchmarks/app/`)

```python
class MockAgentPreHook(PreHook):
    """Stands in for the LLM call: waits a fixed delay and echoes the prompt."""
    def __init__(self, delay_s: float): ...
    async def on_run(self, session, agent, requests) -> AgentReply:
        await asyncio.sleep(self._delay_s)
        return AgentReplyAny(content={"echo": <text of the last AgentRequestText>})
    def name(self) -> str: return "MockAgentPreHook"
```

- Registered first via `Module.pre_hook(agent, [MockAgentPreHook(delay)])` on a minimal OpenAI Agents SDK agent that
  is never called: the runner is never reached, so no LLM request is made. If the SDK insists on an API key at
  construction, a placeholder value is set in the app's environment.
- `delay` comes from `AK_BENCH_AGENT_DELAY_MS`, read once in `agent.py`.
- If Q1 picks a mock `Runner`, this file is replaced by a `MockModule`/`MockAgent`/`MockRunner` trio (bring-your-own
  `Module`), and nothing else in the spec changes.

### 15. Results and plots

- Writers use pandas; timestamps as ISO 8601 UTC with microseconds; durations in ms; empty cells for missing values.
- Column naming for fetcher columns: `<tier>.<count_type>.<fetcher name>`; for queues: `queue.<input|output>.<waiting
  |in_flight>`; for trace stages: `stage.<STAGE>`.
- `Plotter` (matplotlib, PNG, one figure per file) produces exactly the graph list in design.md; the primary fetcher
  is used where a graph needs one line per tier; per-step plots draw part boundaries as vertical lines.

### 16. Phase 2 (`sla/`)

- `PercentileCalculator`: p50/p95/p99 of `latency_ms` (ok rows only) per test type × step, from `requests.csv`;
  appended to a new `percentiles.csv` (the phase-1 CSVs are not rewritten).
- `SlaConfig` (`sla.yaml`): a list of `{metric, host?, mode?, test_type?, step?, op: "<=" | ">=", threshold}`.
- `SlaChecker.check(run_dir, sla) -> sla.csv` with measured value, threshold, pass/fail, and the source file; a metric
  with no measured value is `no_data`, not fail.
- `PerformanceReport`: one Markdown file per host with the SLA table and the main graphs.

### Consumer changes

- **`pipeline/request_handler.py`, `pipeline/ws/handler.py`, `pipeline/agent_runner.py`,
  `pipeline/response_handler.py`, `pipeline/integration_delivery.py`, `integration/adapter/producer.py`, the ECS and
  Lambda files in section 3:** stage-style `self._log.info` lines deleted and trace calls added as listed. No other
  logic changes; the order of sends and acks is unchanged (only log calls move).
- **`core/logger.py`:** one new call in `configure_from_config`.
- **`core/config.py`:** one new model and one new field.
- **Verified unchanged:** every public signature, the queue message envelope, the WS frame shapes, and every
  non-stage log line.

### Config changes

- New `logging.pipeline_trace.enabled: bool = False` (`_PipelineTraceConfig`). Read only by
  `AKLogger.configure_from_config`. Env var `AK_LOGGING__PIPELINE_TRACE__ENABLED`.
- Existing YAML and env vars are unaffected; with the default, logging output differs only by the removed INFO lines.
- The benchmark's own `BenchConfig` is a separate file and model, not part of `AKConfig`.

### Behavioural changes

1. **The stage-style INFO lines listed in section 3 no longer appear in normal logs** (intentional: requirement
   "replace the existing stage logs"). Anyone following a request through INFO logs now enables
   `logging.pipeline_trace.enabled`. No test, doc or skill references them (grep, 2026-10-25).
2. **`[AGENT DONE]` timing moves**: `AGENT_DONE` is logged before the output send instead of after
   (`pipeline/agent_runner.py:57`), and ECS's dequeue line becomes `AGENT_RECEIVED` (intentional: each stage logged
   at its own point).
3. **With the flag on, every pipeline process writes extra lines** on stderr under logger `ak.pipeline_trace`,
   independent of `logging.ak.level` (intentional, opt-in).

**Non-changes:** no change to execution, queue semantics, message attributes, WS frames, public exports or
signatures; the benchmark project ships nothing in the `agentkernel` wheel.

## Error handling

- **AK side:** `PipelineTrace.log` never raises into the pipeline: the logging module's own handler error path
  (`Handler.handleError`) applies, as for any log call. `configure` errors (none expected) propagate at config load,
  like the existing level setup.
- **Config errors** (`BenchConfigError`): unknown host/mode/test type, missing `steady_duration_s`/`load.scaling`,
  Lambda batch × delay over the timeout, `baremetal` without a price only warns (cost left empty). Raised before any
  deploy.
- **Deploy failure:** the host × mode pair is marked failed in `run.log` and the summary of the CLI; teardown still
  runs; the next pair continues.
- **Collector failure** (fetcher, transport, trace, usage, billing, price): caught, logged with the component name,
  columns left empty, the run continues. For the primary fetcher during cool-down, a failed poll counts as "condition
  not met" for that poll, so the step ends at the latest at `max_cooldown_s`.
- **Client errors:** connect failure, socket close mid-request, or an error frame become `status = error` rows; a
  closed socket is reconnected for the next request (steady) with the reconnect time logged.
- **Interrupted run (Ctrl-C):** stops sending, writes whatever was recorded, tears down unless `--skip-teardown`.
- Missing optional tools (`terraform`, `helm`, `kubectl` context) fail the host at deploy with a message naming the
  tool.

## Testing

### AK (`ak-py/tests/`)

- New `tests/test_pipeline_trace.py`:
  - formatter output for a fixed `LogRecord.created` (UTC, microseconds, `Z`), with and without message, with quotes,
    backslashes and newlines in the message;
  - parser round-trip for every `TraceStage`; lines with a CloudWatch / `kubectl --timestamps` prefix; non-trace lines
    and unknown stages → `None`;
  - off by default: `log` emits nothing and does not call the formatter (patch `PipelineTraceFormatter.format`);
  - `configure(True)`: logger level INFO, `propagate is False`, one handler; trace lines appear even with
    `logging.ak.level = WARNING`; nothing reaches the `ak` or root handlers; `configure(False)` removes the handler;
    idempotent;
  - falsy `request_id` → nothing written.
  - An autouse fixture restores `PipelineTrace._enabled` and the `ak.pipeline_trace` logger, like
    `restore_logging_state` in `tests/test_ak_logger.py`.
- `tests/test_ak_logger.py`: new case under `TestConfigureFromConfig` asserting `PipelineTrace.configure` is called
  with the config value (same `AKConfig.get` patch the class already uses).
- `tests/test_config.py`: default `False`; `AK_LOGGING__PIPELINE_TRACE__ENABLED=true` sets it.
- **Riskiest consumers (the moved lines):** one test per traced component asserting the stage sequence for one
  request with tracing on, using `caplog` on `ak.pipeline_trace` (with `configure(True)` and a capturing handler):
  - single-process `in_memory` topology (WS async): extend the existing round-trip style test to assert
    `REQUEST_RECEIVED, INPUT_ENQUEUED, AGENT_RECEIVED, AGENT_START, AGENT_DONE, OUTPUT_ENQUEUED, OUTPUT_RECEIVED,
    RESPONSE_DELIVERED` in that order for one `request_id`;
  - `StreamAgentRunner`: `AGENT_FIRST_CHUNK` once, `OUTPUT_ENQUEUED` once;
  - ECS and serverless components: one tracing case each in the existing files, reusing their SQS mocks:
    `tests/test_ecs_akagentrunner_stream.py` (ECS agent runner, stream and non-stream),
    `tests/test_ecs_akoutputconsumer.py` (ECS output consumer), `tests/test_akagentrunner_stream.py` and
    `tests/test_serverless_status_propagation.py` (serverless agent runner), `tests/test_akresponsehandler.py`
    (serverless response handler). The WS enqueue paths (`websocket_api.py`, `ws_lambda.py`) get a case in whichever
    file already covers `_enqueue_chat` / `_handle_queue_mode`, or a new `tests/test_pipeline_trace_points.py`.
- Run: `cd ak-py && uv run pytest tests/test_pipeline_trace.py tests/test_ak_logger.py tests/test_config.py` then the
  full suite; `make lint-check-all`.

### Benchmark (`benchmarks/tests/`)

- Unit tests with fakes, no cloud calls:
  - `test_step_end.py`: each condition alone and together; missing sources; SQS settle window; max cool-down;
    Lambda missing-datapoint rule.
  - `test_windows.py`: samples and spans → columns; overlapping spans; empty windows stay empty.
  - `test_derived.py`: scale-up/down times and counts on hand-made series, including "never scaled down" and "didn't
    scale".
  - `test_cost.py`: pro-rata overlap, per-step totals, cost per 1M with zero ok, cost model.
  - `test_traces.py`: join, duplicates (earliest wins), derived durations.
  - `test_config.py`: validation errors listed in Error handling.
  - `test_factories.py`: driver/host built-ins, dotted path, unknown name message.
  - `test_ws_complete_driver.py`: against a local `websockets` server that replays recorded frames.
- `test_local_smoke.py` (opt-in, `AK_BENCH_LOCAL=1`): starts the app in the single-process `in_memory` topology with
  tracing on, runs burst steps 1 and 10 with 0 ms delay, and asserts the four CSVs exist, every request has a status,
  and every ok request has all eight stage columns.
- Cloud collectors (`aws/`, `k8s/`) get unit tests over `botocore.stub.Stubber` / a fake K8s client for the parsing
  of their responses only.
- Run: `cd benchmarks && uv run pytest`.
- No CI workflow change in phase 1. The AK-side tests run in the existing `ak-py` suite.
