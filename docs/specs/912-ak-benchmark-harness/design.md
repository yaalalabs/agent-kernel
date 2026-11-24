# #912: Benchmark harness (`ak-bench` core)

Builds the shared, cloud-independent part of the #786 benchmark system: the `ak-bench` CLI in a new top-level
`benchmarks/` project, the mock agent app, the load generator with the WebSocket complete driver, the `InfoFetcher`
base and its five families, the step runner and step-end check, the commands and their state, the CSVs, derived
numbers and graphs. Nothing here calls a cloud API; every part is tested with a mock host (mock deployment folder, mock
fetchers) and a local mock WebSocket server. The AWS deployment folders and fetchers come in their own issues and plug in
without harness changes.

The system design is `docs/specs/786-benchmark-system/design.md` (PR #893); this document cites its sections instead
of restating them, and only adds what the harness build needs to pin down. Part of #917; uses the trace parser from
#911.

## Motivation

- #786 defines what the benchmark measures and how a run flows; nothing of it exists yet (no `benchmarks/` directory).
  The AWS host issues under #917 need the shared harness first, so they only add deployment folders and fetchers.
- Precedent for a standalone project outside the `agentkernel` package: `e2e/app/pyproject.toml` (uv,
  `package = false`, depends on published `agentkernel[...]`, `:8`).
- The trace parser the `TraceCollector` family needs is in place from #911 (on this branch, not yet on `develop`):
  `TRACE` (`ak-py/src/agentkernel/core/logger.py:12`), `TraceStage` (`:16`), `TraceLine.parse()` (`:47`), which
  returns `None` for non-trace lines and unknown stages.
- AK's factory helpers give the registry shape to reuse: `resolve_dotted()` (`core/util/factory.py:27`),
  `AKConfigError` (`:19`).
- The mock agent needs no AK change:
  - `Runner` ABC (`core/base.py:337`) with abstract `run()` (`:491`) and `stream()` (`:574`).
  - `Runtime.run` calls `agent.runner.run()` (`core/runtime.py:546`), then saves the session (`:555`), so hooks and
    the session save still run around the mock delay.
  - Same shape as `DummyRunner` / `DummyAgent` (`ak-py/tests/test_pipeline_request_handler.py:35,51`); reply type
    `AgentReplyAny` (`core/model.py:216`).
- The client can set `request_id` itself: the shared WS handler uses the frame's `request_id` when given
  (`pipeline/ws/handler.py:254`); the Lambda WS path requires one (`deployment/aws/serverless/core/router/ws_lambda.py:405-406`).
- Replies are pushed to every connection of the reply's user (`pipeline/response_handler.py:282-284`), and the user
  is the connection's authenticated principal (`pipeline/ws/handler.py:148-152`), so clients must never share a user.
- A WebSocket connection without a `token` query parameter, or with one the identity provider refuses, is closed
  (`pipeline/ws/handler.py:192-212`).
- Deploying with a `deploy.sh` next to the Terraform files is the repo's existing pattern
  (`examples/aws-serverless/websocket-openai/deploy/deploy.sh`), so a deployment needs no Python deployer class.
- The built-in `static` provider needs one stored secret per user (`identity/provider/static.py:43-56`, values must be
  unique, `:52-54`): 1000 clients would mean 1000 secrets. A bring-your-own provider is a dotted path in
  `identity.provider.type` (`identity/provider/factory.py:57-59`) and reads its own settings from the provider block
  (`core/config.py:1489-1490`).

## Requirements

### Project

- New top-level `benchmarks/` directory, its own `pyproject.toml` (uv), not part of the `agentkernel` package.
  - Console script `ak-bench`.
  - Depends on `agentkernel` from the repo's `ak-py/` (uv path source), for `TraceStage` and `TraceLine`, so the
    harness and its CI tests always use the parser that matches the branch's log format. Data and plotting libraries
    (numpy, matplotlib) are this project's dependencies only. No cloud SDK is needed by anything in this issue.
  - Layout (one file per implementation, per #786 Hosts and `Scratches/25.Benchmarking-Design/implementation/code-layout.md`):
    - `platforms/base.py`: `InfoFetcher`, the five family bases and their dataclasses, `Fetchers`, `Deployment`,
      `Host`.
    - `hosts.py`: the host registry.
    - `load/`: load generator, `ClientDriver`, the WebSocket complete driver, the driver factory.
    - `run/`: `commands.py` (one class per command), `state.py` (`DeploymentState`), `step_runner.py`
      (`StepRunner`), the run log.
    - `scaling/`: `collector.py`, `derived.py`, `step_end.py` (`StepEndCheck`).
    - `resources/collector.py`; `cost/report.py`; results writers and plots.
    - `app/`: the benchmarked AK app with the mock agent, a separate uv project with its own `pyproject.toml`
      (like `e2e/app/`), since it is deployed and the harness is not. One Python code base for every host.
    - `app/deploy/<host>-<mode>-<message-type>/`: one deployment folder per host × mode × message type (e.g.
      `lambda-async-complete/`), holding its Terraform files, `deploy.sh` and `destroy.sh` (see Deployment folders).
      The real folders come with the AWS issues; this issue adds a mock one for the tests.
    - `tests/`: mock host, mock fetchers, mock deployment folder, local mock WebSocket server.
- Every component is a class with one responsibility; module-level functions only for small stateless helpers
  (e.g. percentile computation), each justified in `spec.md`.

### Configuration (`ak-bench.yaml`)

- Its own config file, not `AKConfig` (departure from the config-reuse house pattern already accepted in #786:
  benchmark settings, not AK runtime config).
- Read into one Pydantic model (`BenchConfig`) with every key of the #786 example (Benchmark project) and the
  defaults listed there, plus two new keys under `step_run` (below), and no others.
- New keys for the step-end check (were fixed values in `StepEndCheck`):
  - `step_run.cooldown_poll_interval_s`, default `10`: time between two cool-down polls.
  - `step_run.cooldown_lookback_s`, default `180`: how far back each `cooldown_checks` `fetch()` reads
    (window `(now − lookback, now)`), so sources that report per period (e.g. 1-minute metrics) still return their
    latest value.
  - Keys marked "no default" there (`step_run.time_window_s`, `fetchers.default.poll_interval_s`) are required;
    a missing one is a load-time error naming the key.
  - Unknown keys are refused, naming the key.
- `fetchers.<name>.poll_interval_s`, else `fetchers.default.poll_interval_s`, is the poll interval of the fetcher
  registered as `<name>` when it runs in `during_step`.
  - A `<name>` that no fetcher of the selected hosts has (e.g. a typo, `aws.ecs-api`) is refused before anything is
    deployed, naming the key and the known fetcher names.
- `host_settings.<host>.max_cooldown_s`, when set, overrides `step_run.max_cooldown_s` for that host.
- `mock_agent`:
  - both `min_delay` and `max_delay` set → mock agent;
  - block left out, or neither set → real agent;
  - only one set → `deploy` refuses before deploying, naming the missing key;
  - `min_delay > max_delay` or a negative value → `deploy` refuses, naming the key.
- `hosts`, `modes`, `message_types`, `test_types`, `load_steps` stay in the config and the CLI (#786 L3: drop one side
  during implementation only if it proves redundant, and record it).

### Registries

- Host registry and driver factory: **built-in names only**, no bring-your-own (decided 2026-11-23): only the AK team
  runs the benchmark, so a new host or driver is added as a new built-in. Departure from the pluggable-by-default
  house pattern.
  - An unknown name raises an error naming the built-ins.
- Host registry: name → `Host`. No built-in hosts in this issue (`ecs` / `lambda` come with the AWS issues); the
  registry and its error are tested with a mock host registered by the tests.
- Driver factory: keyed by mode × message type; one built-in, `async` + `complete` (WebSocket complete).

### Mock agent app

- `MockRunner(Runner)` and `MockAgent(Agent)` in `benchmarks/app/`, registered with the runtime like any agent. No AK
  code change.
- `MockRunner` reads its delays once, at creation, from `BenchAppConfig` (the app's own settings class, separate from
  `AKConfig`), which loads `AK_BENCH_MOCK_AGENT_MIN_DELAY_S` and `AK_BENCH_MOCK_AGENT_MAX_DELAY_S`.
- `run()`: `await asyncio.sleep(random.uniform(min_delay, max_delay))`, drawn per request, then returns
  `AgentReplyAny(content={"echo": <prompt>})`.
- `stream()`: the same delay, then the echo as stream events (unused by WebSocket complete; for delta later).
- No per-request state on `self`; no timing; adds nothing to the session.
- The app registers `MockAgent` only when both variables are set, otherwise its real agent.
- App config: `session.type: in_memory`, `logging.ak.level: TRACE`, queue execution, WebSocket delivery, no hooks
  configured on the agent.

### Client authentication (signed tokens)

- `BenchIdentityProvider(IdentityProvider)` in `benchmarks/app/`, named in the app's config as
  `identity.provider.type: <its dotted path>`. No AK code change.
- **One auth token per user, one user per token.** A client (one simulated user with its own WebSocket
  connection) is numbered 1..N; its user (the `user id` column in the CSVs) is `bench-<N>`; its token is
  `<user>.<signature>`, where `signature` = hex HMAC-SHA256 of the user name with the deployment's signing secret.
  - The same user always gets the same token; the user name is inside the token, so a token maps to one user only.
- **Signing secret:** one random secret per deployment (at least 32 bytes), made by `deploy`.
  - Stored in the cloud's secret store, never as an environment variable on the deployed components: `deploy`
    passes it to `deploy.sh`, whose Terraform creates the secret resource (AWS: an SSM Parameter Store
    `SecureString`) and gives every component read access to it.
  - The app reads it through AK's secret capability (AWS: `secret.provider.type: aws_ssm`): the provider block names
    the key (`secret_key: AK_BENCH_AUTH_SECRET`), resolved once when the provider is built. No component may set an
    `AK_BENCH_AUTH_SECRET` environment variable, since a set variable wins over the store (`core/config.py:1411`).
  - Every component gets read access, not only the WebSocket handler: AK builds the identity provider on demand in
    other places too (`api/handler.py:64`), and this provider fails at build without its secret.
  - The load generator gets it from `state.json`, so `step` can sign tokens without redeploying.
  - It only opens a deployment that `finish` tears down, so it is not kept anywhere after the run.
- `authenticate(credential)`:
  - splits the token at the last `.` into user and signature;
  - recomputes the signature and compares it with `hmac.compare_digest` (constant time);
  - match → `Principal(subject=<user>, kind="user", provider="bench", namespace="bench")`;
  - no `.`, an empty part, or a wrong signature → `AuthenticationError`, so the connection is closed.
- A missing or empty secret is a startup error of the provider (raises when built), not a provider that refuses
  every connection.
- `TokenSigner` (harness side, in `load/`): makes `<user>.<signature>` from the secret. The app and the harness are
  separate projects, so each writes the one-line signing rule; a test checks that a `TokenSigner` token is accepted
  by `BenchIdentityProvider`.
- Each client's session id is new per step; users repeat across steps (`bench-1` in step 1 and step 10), which is fine
  because steps never overlap.

### Load generator and client driver

- `ClientDriver` ABC: `connect()` → `send(request)` → receive response events → `close()`.
  - Every driver reports the same timing events per request: sent, first chunk, complete. For a mode with no chunks,
    first chunk = complete.
  - Built-in: the WebSocket complete driver, speaking AK's WebSocket chat frame.
- `LoadGenerator` (asyncio), shared by every mode:
  - Opens all N client connections **before the step's `before` part starts** (`connect()` per client), so connect
    time is never part of latency and `before` records the idle values with the sockets already open. `before`
    starts once every connect has finished or failed. Connections stay open until the cool-down ends, then close.
  - Starts the N clients' sends at the same moment; each client has its own user identity and its own session id.
    Clients never share a user.
  - **One auth token per user, one user per token** (decided 2026-11-23): each client authenticates with exactly
    one token, the same one for its whole connection, and no other client gets a token for that user. So N clients
    = N users = N tokens.
  - Sets each `request_id` itself (unique per request) and puts it in the prompt the mock agent echoes.
  - Sending and receiving run separately; responses are matched to requests by `request_id`. A send never waits for
    a response.
  - Records per request, on the client clock: scheduled send, sent, first chunk, complete, status
    (`ok` / `error` / `timeout`).
    - Timestamps are UTC wall-clock time (so they line up with AK's UTC trace lines); latency and every other
      duration on the client side come from a monotonic clock, so a clock adjustment during a step can't distort
      them.
  - One load-generator process runs all N clients (asyncio); "client" means one simulated user with its own
    connection, not one process.
  - After `client_timeout_s` from sent with no complete, stops waiting and records `status = timeout`.
  - A failed connect or send records `status = error` for that client's requests; the step carries on.
- Burst: each client sends one request; records the time to answer all N (first send → last response or timeout).
- Steady: each client draws its own gaps, uniform between `min_send_interval_s` and `max_send_interval_s`
  (min = max = fixed interval), for `load_time_s` from the first send.
  - Next send = previous **scheduled** send + gap; a late send doesn't shift later ones.
  - No send is scheduled after `load_time_s`.
- Fetcher work never runs on the load generator's event loop (see Step runner), so polls don't delay sends.

### `InfoFetcher` and families

- `InfoFetcher[T]` (ABC, generic):
  - constructor: `poll_interval_s` (None = from `ak-bench.yaml`), `settle_window_s` (default 0);
  - `name`: the registered name, used in CSV column names and `fetchers.<name>` config;
  - abstract `fetch(run, deployment, start, end) -> T`: the only method a platform subclass writes; reads, stores
    nothing; synchronous;
  - abstract `store(result, results)`: written once per family;
  - `is_settled(now, start) -> bool`: not implemented on the base;
  - `fetch_and_store(run, deployment, start, end, results)`: `fetch()` then `store()`; raises an error naming the
    fetcher, the expected and the returned type when `fetch()` returned another type.
- A value the source gives per period is stored with `ts` = the end of that period (#786 Hosts); set in `fetch()`.
- Family bases, each fixing `T` and writing `store()` once:

  | Family | `T` (dataclass) | `store()` writes | `is_settled()` |
  |---|---|---|---|
  | `ScalingInfoFetcher` | `ScalingInfo` (`CountSample`s, `WorkerSpan`s) | `scaling-samples.csv`, `worker-spans.csv` | every tier's latest `running` count == its starting count |
  | `ResourceUsageFetcher` | `ResourceUsage` (`ResourceSample`s) | `resource-usage.csv` | – |
  | `TraceCollector` | `TraceInfo` (`{request_id: {stage: ts}}`) | `stage-timestamps.csv` | – |
  | `TransportCollector` | `QueueInfo` (`QueueDepth` samples) | `queue-depth.csv` | every queue's latest reading has 0 waiting and 0 in flight (start unused) |
  | `CostFetcher` | `CostInfo` (`CostItem`s) | `cost.csv` | – |

  - `ScalingInfoFetcher` also has `count_types` (e.g. `{"desired", "running"}`).
  - Dataclass fields as in #786 Scaling, Resource usage, Cost and `Scratches/25.Benchmarking-Design/implementation/code-layout.md`.
- No duplicate rows: `store()` writes by key and replaces a row with the same key instead of adding it:
  - counts: `ts, tier, count_type, fetcher`; spans: `tier, worker, fetcher` (latest wins);
  - resource usage: `ts, tier, worker, metric, stat, fetcher`; queue depth: `ts, queue, fetcher`;
  - stage timestamps: `request_id, stage`; cost: `period_start, period_end, service, metric, fetcher`.
- `store()` is safe when two fetchers write the same file at once (`during_step` tasks run in parallel threads).
- `Fetchers`: the five lists `during_step`, `cooldown_checks`, `after_step`, `after_all_steps`, `after_teardown`; one
  fetcher object can be in several. Each list passes its own window to `fetch()`:
  - `during_step`: (last poll, now); `cooldown_checks`: (now − `cooldown_lookback_s`, now);
  - `after_step`: (step start, step end); `after_all_steps`: (deploy start, now);
    `after_teardown`: (deploy start, teardown end).
- `Fetchers.validate(host)`, run when the host is loaded, before anything is deployed; refuses the host, naming the
  host and the fetcher, when:
  - a fetcher in `cooldown_checks` doesn't override `is_settled()`;
  - a `ScalingInfoFetcher` in `cooldown_checks` doesn't have `"running"` in `count_types`.
- A fetcher that raises in a storing list leaves its columns empty, writes a run-log entry (fetcher, list, error),
  and the run carries on. This includes the wrong-type error from `fetch_and_store()`.

### Deployment folders, deployment and hosts

- **No deployer class** (decided 2026-11-23, replaces #786's `Deployer` ABC): deploying is the job of the deployment
  folder's scripts. `deploy` picks `app/deploy/<host>-<mode>-<message-type>/` and runs its `deploy.sh`; `finish`
  runs its `destroy.sh`. A missing folder or script is refused before anything runs, naming the path.
- Script contract, the same for every folder:
  - inputs as environment variables of the script process: `AK_BENCH_DEPLOYMENT_ID` (the tag value
    `<run-id>-<host>-<mode>-<message-type>`), `AK_BENCH_AUTH_SECRET`, `AK_BENCH_MOCK_AGENT_MIN_DELAY_S` /
    `AK_BENCH_MOCK_AGENT_MAX_DELAY_S` (only for the mock agent), `AK_BENCH_HOST_SETTINGS` (JSON of
    `host_settings.<host>`), `AK_BENCH_OUTPUT` (where `deploy.sh` writes its result);
  - `deploy.sh` writes `deployment.json` to `AK_BENCH_OUTPUT`: `endpoint` (URL), `resources` `{tier: ids}`,
    `queues` `{"input": ids, "output": ids}`, `logs` `{component: source}`, `settings` (the host values for
    `run-metadata.json`);
  - exit code 0 = done; anything else = failed (see Commands and state);
  - Terraform state is kept per deployment id (e.g. a workspace named after it), so two deployments of the same
    folder never share state.
- `Deployment` dataclass, read from `deployment.json`: `endpoint` (URL only; tokens come from Client
  authentication), `resources`, `queues`, `logs`, `settings`; saved in `state.json` and read back unchanged.
- `Host` dataclass: `platform`, `fetchers` (`Fetchers`). The harness never branches on host kind.
- The harness imports no cloud SDK; it only runs the scripts and reads `deployment.json`.

### Step runner (`StepRunner`)

- Runs one step: connect → `before` → `load` → `cool-down` → wait + fetch (#786 Step timeline, with the client
  connections opened first; see Load generator). The step start (and its graphs' time axis) is the start of `before`.
- `before` lasts `before_window_s`; live tracking starts at its start.
- Live tracking: one background task per `during_step` fetcher, from the start of `before`:
  - `fetch_and_store(last poll, now)` every `poll_interval_s`, each in a worker thread;
  - at step end: stop flag, one last `fetch_and_store`, then any task not done within 30 s is cancelled.
- Starting values: at the end of `before`, one plain `fetch()` per `cooldown_checks` fetcher, kept in memory, nothing
  stored. A failed read here = no starting value; that fetcher's check is not met until the maximum cool-down.
- `load`: the load generator runs the test type. `t_load_up` = first send; `t_load_down` = end of load (steady: when
  `load_time_s` is up, i.e. `t_load_up` + `load_time_s`; burst: last response or timeout).
- `cool-down`: runs `StepEndCheck` every poll until it passes or the maximum is reached.
- After the step: wait `after_step_wait_s`, then `fetch_and_store(step start, step end)` once per `after_step`
  fetcher.
- At the end of each step with at least one timed-out request, a `WARNING` in the run log: "responses for `<count>`
  requests were not received within the timeout of `<client timeout>`". Log only.
- Then writes the step's CSVs, its `summary.csv` row and `step-metadata.json`, and releases the step lock.

### Step-end check (`StepEndCheck`)

- Runs every `cooldown_poll_interval_s`; the step ends when every check holds in the same poll, checked in order, a later check
  only once the earlier ones hold:
  1. built in, always first: every request of the step has a response or timed out;
  2. each `cooldown_checks` fetcher in list order: `fetch()` + `is_settled(now, start)`; nothing stored.
- `settle_window_s`: `is_settled()` must have held in every poll of the last `settle_window_s` (0 = this poll only).
- A read that raises or returns no value = not met in this poll, a run-log entry, and restarts that fetcher's settle
  window.
- Empty `cooldown_checks`: the step ends once every request is settled.
- Maximum cool-down (from `t_load_down`, `max_cooldown_s` with the host override): the step ends anyway and records
  `cooldown_max_reached = true`.
- Only decides when the step ends; never changes load or deployment.

### Commands and state

- One class per command (`Deploy`, `Step`, `Plot`, `Finish`, `PostRun`, `Run`); `Run` calls the others.
- `DeploymentState` reads / writes `state.json`: the `Deployment`, the load steps, step windows, the step lock, deploy
  start and teardown time.
- `deploy --host --mode --message-type [--run-id]`:
  - new run id unless `--run-id`; refuses a host × mode × message type that already has a deployment in that run;
  - checks the `mock_agent` rules, `Fetchers.validate()` and the deployment folder before deploying;
  - makes the signing secret, runs `deploy.sh`, reads `deployment.json`;
  - writes `run-metadata.json` and `state.json`; prints the deployment id `<run-id>-<host>-<mode>-<message-type>`;
  - if `deploy.sh` fails, runs `destroy.sh` for what it may have created, records the failure in the run log, and
    exits with an error.
- `step --deployment --test-type steady|burst --step <N> [--replace]`:
  - `--step` must be one of the load steps saved in `state.json`;
  - refuses while another live process holds the step lock (process id + machine); a lock whose process is gone on
    the same machine is stale and taken over, with a run-log entry;
  - `step --deployment <id> --force-unlock` (decided 2026-11-23) clears a lock held from **another machine**, which
    this machine can't check: it prints who held the lock and since when, asks for confirmation (`--yes` skips the
    prompt), clears it, writes a run-log entry, and runs no step. Documented in the command's `--help` and in the
    testing checklist (when to use it: only once the step on the other machine is known to be dead);
  - refuses an existing step folder unless `--replace` (which replaces the folder and the `summary.csv` row);
  - no warm-up option, and `run` runs no warm-up step (decided 2026-11-23); if a run needs one, it's added by hand
    to the run script (#786 Selecting what to run).
- `plot --deployment` or `--run-id`: draws every graph from the CSVs so far into the same `graphs/` folders.
- `finish --deployment`: runs `after_all_steps` (re-plots if it stored anything), runs `destroy.sh`, records the
  teardown time, prints whether `post-run` is needed (non-empty `after_teardown`). A `destroy.sh` failure is
  recorded in the run log and `finish` exits with an error, so the person knows resources may be left running.
- `post-run --deployment` or `--run-id`: runs `after_teardown` for (deploy start, teardown end), fills its CSVs,
  re-plots; can be run again (rows replace by key).
- `run [--host] [--mode] [--message-type] [--steps]`: each repeatable, default all; every `--steps` value checked
  against `load_steps` before anything is deployed; then per host × mode × message type: deploy → steps in the default
  order (steady N, then burst N, then the next N, for the configured test types) → plot → finish.
- **Failures never leave a deployment running unnoticed** (decided 2026-11-23):
  - `run`: if a step fails or the run is interrupted (Ctrl-C), it still runs `finish` (teardown) for that deployment
    before exiting; a second Ctrl-C during teardown is the only way to skip it, and that is logged.
  - `step`: releases its lock on every exit (done, error, Ctrl-C); a failed step leaves its partial folder and no
    `summary.csv` row.
- `run.log` per run (`results/<run-id>/run.log`); every command appends to it.
- `run-metadata.json` (from `deploy`, host values from `deployment.json` `settings`, a missing value stays empty) and
  `step-metadata.json` (per step) carry the fields in #786 Run flow → Run metadata.

### Results, derived numbers and graphs

- Folder layout `results/<run-id>/<platform>/<host>/<mode>/<message type>/<test type>/step-<N>/` (#786 Results):
  - `step-<N>` zero-padded to the digits of the largest load step saved in `state.json`;
  - only what ran gets a folder.
- Percentiles: p0 / p25 / p50 / p75 / p99 / p100 only, numpy `method='linear'`, over requests (never per worker
  first).
- `per-request.csv`: request id, session id, user id, scheduled send, sent, first chunk, complete, latency
  (`complete − sent`), status, raw stage timestamps, one `<STAGE>_s` per request-path `TraceStage` (not
  `RESPONSE_POLL_START` / `RESPONSE_FOUND`) plus `CLIENT_RECEIVED_s`.
  - Duration = previous request-path stage → this stage; `CLIENT_RECEIVED_s` = `RESPONSE_DELIVERED` → complete;
    empty when either point is missing.
- `per-time-window.csv`, windows of `time_window_s` from the step start: step part, Tx, Rx, errors, timeouts,
  latency percentiles of requests completed in the window, each queue's depth, worker counts per
  tier × count type × fetcher (e.g. `runner.running.aws.ecs_api`), CPU / memory per tier × metric × stat × fetcher.
  - Each window takes each series' last sample at or before the window's end, carried forward for at most the
    fetcher's poll interval (or the source's sample period); after that the window is empty.
- Raw fetcher files in the step folder, written by the family `store()` and read by the collectors:
  - `scaling-samples.csv` (`ts, tier, count_type, value, fetcher`);
  - `worker-spans.csv` (`tier, worker, started, stopped, extra, fetcher`);
  - `queue-depth.csv` (`ts, queue, waiting, in_flight, fetcher`);
  - `stage-timestamps.csv` (`request_id, stage, ts`);
  - `resource-usage.csv`: raw samples, long form (`ts, tier, worker, metric, stat, value, fetcher`).
- `summary.csv`, one row per step (each `step` writes or replaces its own row): latency and stage-duration
  percentiles with the row count used, min / avg / max of per-window Tx / Rx, error and timeout counts, time to answer
  all N (burst; empty for steady), `cooldown_max_reached`, scaling numbers and CPU / memory per tier per fetcher.
- Derived scaling numbers per step × tier × fetcher, from raw sample times (not windows), definitions as in
  `docs/specs/786-benchmark-system/research/platform-scaling-and-cost.md` (Derived numbers):
  - decision delay, first new worker, scale-up done, backlog drained, scale-down start, scale-down done;
  - `workers_before_up`, `workers_peak`, `workers_before_down`, `workers_after_down`;
  - rate in workers / min; never divides by 0; empty for a step that didn't scale; a count with no source stays
    empty.
- Graphs (PNG), as listed in #786 Graphs, with its drawing rules:
  - per test type: `01-latency-per-step`, `02-stage-times-per-step`, `03-resource-usage-per-step`;
  - per step: `01-stage-times`, `02-stage-breakdown`, `03-timeline`, `04-every-request` (steady only),
    `05-resource-usage`;
  - billed cost per run by service (`cost/report.py`), drawn when `cost.csv` exists.
  - A graph whose data is all empty (e.g. no CPU source) is still drawn with empty panels, not skipped.
- `Scratches/25.Benchmarking-Design/graph-examples/plot_examples.py` is the reference for layout, not production
  code.

### Testing

- All tests run without a cloud account: a mock deployment folder (scripts that write a `deployment.json` pointing
  at the local mock server), mock fetchers of each family, a mock host, a local mock WebSocket server that echoes by
  `request_id` with a set delay (and can drop replies).
- Covered (the issue's acceptance criteria):
  - a full deploy → step → plot → finish → post-run cycle against the mock host;
  - burst sends one request per client, all N at once; steady follows the scheduled-send rule;
  - step-end order, settle window, failed read restarting the window, max cool-down, stale-lock takeover, `--force-unlock`;
  - `Fetchers.validate()` refuses an invalid host before deploy;
  - a failing fetcher → empty columns, run-log entry, run carries on;
  - the missing-responses `WARNING`;
  - `step` refusals (existing folder without `--replace`, step not in saved load steps, concurrent step);
    `run --steps` refuses an unknown value before deploying;
  - `store()` replaces a row with an existing key;
  - every CSV and every phase 1 graph produced from recorded data;
  - `MockRunner` delay bounds, echo content, and mock-vs-real selection;
  - `BenchIdentityProvider`: a signed token gives its user; a changed user name, a changed signature, a token without
    `.` and an unsigned token are refused; a missing secret fails at build; `TokenSigner` gives the same token for the
    same user every time;
  - connections are opened before `before` starts, and a failed connect records `status = error`;
  - teardown runs when a `run` step fails, when `run` is interrupted, and when `deploy.sh` fails; the step lock is
    released on a failed step;
  - an unknown `fetchers.<name>` key and a missing deployment folder are refused before anything runs.
- The harness tests run in CI: a step in `.github/workflows/test-reusable.yaml` (called by `test.yaml` on every PR
  and push to `develop`) runs `uv run pytest` in `benchmarks/`. Only the cloud-free tests; no benchmark run.

## Non-goals

- Real deployment folders and fetchers, and the `ecs` / `lambda` host entries (AWS issues).
- WebSocket delta and `rest_async` drivers (later; new driver class + factory branch, no harness change).
- Any AK change (the `TRACE` level and trace points are #911).
- Running the benchmark itself in CI (only the harness's own tests run there).
- Everything #786 lists as a non-goal (flagging, early stops, load-generator health, cross-host graphs, ...).

## Open questions

Resolved 2026-11-23: O1 (connect before `before`), O4 (raw file names), O5 (two new `step_run` keys with defaults),
O6 (`benchmarks/app/` as its own project), O7 (harness tests in the test workflow), O3 (no bring-your-own driver:
built-ins only), O2 (signed tokens, one per user; see Client authentication); written into the requirements above.

- **O8. CI for the app's tests** (`benchmarks/app/`: `MockRunner`, `BenchIdentityProvider`): the test-workflow step
  above runs `benchmarks/` only. Decide at the end of the task whether it also runs `benchmarks/app/`.
