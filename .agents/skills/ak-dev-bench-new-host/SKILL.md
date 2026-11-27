---
name: ak-dev-bench-new-host
description: >
  Step-by-step guide for adding a new host to the ak-bench benchmark harness (benchmarks/): a new place the
  benchmarked AK app is deployed and measured, e.g. ecs, lambda, EKS, GKE, Cloud Run or Azure Container Apps.
  Use this skill when ak-bench must deploy to and measure a platform it doesn't support yet, or when an existing host
  needs a deployment folder for another execution mode. Covers the host bundle and its five StageFetchers lists, the
  HostRegistry entry, the deployment folder (deploy.sh, destroy.sh, deployment.json, Terraform state, the auth
  secret), host_settings, and tests.
license: Apache-2.0
metadata:
  author: yaalalabs
  category: developer
---

# Adding a New Host to ak-bench

A host is **not a class**. It is a registry entry: a platform name plus a `StageFetchers` bundle that picks existing
fetchers and says where in the run each one runs. Deploying is done by a deployment folder's shell scripts, not by
Python. Read `ak-dev-bench-architecture` first if you haven't.

A host is three things:

1. the fetchers it needs (existing ones, or new ones via `ak-dev-bench-new-fetcher`);
2. its bundle in `benchmarks/ak_bench/hosts/<platform>.py`, registered in `HostRegistry`;
3. one deployment folder per mode × message type in `benchmarks/app/deploy/<host>-<mode>-<message-type>/`.

## Step 0: Research the platform (before any code)

Follow the workflow in `ak-dev-bench-architecture` (baseline, research rules, recording, when to ask). For a host,
find out from the platform's official docs and from this repo:

- **How AK runs there**: which AK entry points serve each tier (read `ak-py` and `ak-deployment/` for an existing
  module or chart to reuse), which tiers exist (request handler, agent runner, response handler, ...), and how the
  queue mode is wired (transport, queues).
- **Autoscaling**: what scales (tasks, functions, pods, replicas), on what signal, its defaults and limits (min /
  max, cooldowns, scale-down delays, concurrency per worker), so the deployment folder sets the #786 benchmark
  settings explicitly instead of relying on defaults. These settings go into `deployment.json` `settings.tiers`.
- **Front door**: what clients connect to (API Gateway WebSocket, load balancer, ingress), its connection and idle
  limits, message size and integration timeouts, and whether it supports the modes you deploy.
- **Quotas that cap the load steps**: account / project limits on concurrency, connections, tasks, request rates.
  Note which load step would hit them; raise or record them, never work around them in the harness.
- **Secret store** and how AK's secret capability reads it (`ak-py/src/agentkernel/secret/`), for the auth secret.
- **Where logs go** (for TRACE lines and log-based fetchers) and the log retention to set.
- **Each fetcher family**: the source per family (run the fetcher skill's research for every one not yet written).
- **Cost**: how resources are tagged or labelled, whether cost can be filtered by that tag, the billing delay
  (when the bill for a run is final), one-time account setup (e.g. activating a cost allocation tag), and what is
  billed that the tag won't catch.
- **Teardown completeness**: resources the platform creates outside Terraform (log groups, ENIs, images, snapshots)
  that `destroy.sh` must also remove.
- **Prerequisites for the person running it**: CLI tools, credentials, region / project, permissions.

Record findings with source links in `docs/specs/786-benchmark-system/research/` (one file per platform is fine) and
the chosen settings in the #786 Hosts section. Building a host costs money to test: plan the by-hand run and get the
person's go-ahead before deploying.

## Step 0b: Decide what to measure and where it comes from

For the new host, answer per family (write the answers into the #786 design's Hosts section, verified against the
platform's official docs):

| Question | Family | Typical list |
|---|---|---|
| How many workers per tier are running / desired, and when did each start and stop? | scaling | `during_step` if only current values, `after_step` if history |
| CPU and memory per worker or tier? | resources | `after_step` |
| Where do the app's `TRACE` lines go? | trace | `after_step` |
| What is the transport, and how is queue depth read? | transport | `during_step` + `cooldown_checks` |
| How is cost read, and when is it final? | cost | `after_teardown` (billed later) or `after_all_steps` |
| Which fetcher tells the cool-down the workers are back to their starting count? | scaling with `"running"` | `cooldown_checks` |

Reuse before writing: fetchers are grouped by the system they call, so an EKS host reuses Kubernetes scaling
fetchers, AWS cost and the SQS collector; a GKE host reuses the same Kubernetes fetchers with GCP cost. Write a new
fetcher only for a source nothing reads yet.

## Step 1: The host bundle (`hosts/<platform>.py`)

One file per platform holds every host of that platform, so shared fetcher objects are built once:

```python
from ak_bench.fetchers.core.stage_fetchers import StageFetchers
from ak_bench.hosts.host import Host

# One object per fetcher, shared by lists and hosts (fetchers are stateless)
sqs = SqsTransportCollector(session, settle_window_s=60)       # approximate counts -> must hold 60 s
traces = CloudWatchLogsTraceCollector(cloudwatch_logs)
cost = CostExplorerCostFetcher(session)
ecs_api = EcsApiScalingInfoFetcher(session)

HOSTS: dict[str, Host] = {
    "ecs": Host(
        platform="aws",
        fetchers=StageFetchers(
            during_step=[ecs_api, sqs],
            cooldown_checks=[sqs, ecs_api],     # run in this order, after the built-in "all requests settled"
            after_step=[traces, EcsScalingActivitiesScalingInfoFetcher(session), ...],
            after_all_steps=[],
            after_teardown=[cost],              # run by `ak-bench post-run`
        ),
    ),
}
```

Then register it in `hosts/registry.py`:

```python
from ak_bench.hosts import aws

class HostRegistry:
    _BUILTINS: ClassVar[dict[str, Host]] = {**aws.HOSTS}
```

Rules:

- **Host name:** lowercase, `[a-z0-9_]`, **no `-`**. The deployment id `<run-id>-<host>-<mode>-<message-type>` is
  split on `-` (`DeploymentState.locate`), and the name is also the deployment folder prefix, the
  `host_settings.<host>` key and a results path segment.
- **`platform`** is the cloud the host runs on (`aws`, `gcp`, `azure`, ...). It is only a results-path segment
  (`results/<run-id>/<platform>/<host>/...`) and run metadata; nothing branches on it.
- **No host-specific code.** If you're tempted to add an `if host == ...` anywhere in `run/`, `load/` or `results/`,
  the difference belongs in a fetcher, the bundle's lists, or the deployment folder instead.
- **Import must be offline.** Every command and test imports the registry, so building the bundle must not call a
  cloud or need credentials or a region.
- **Validation is automatic.** `HostRegistry.get()` runs `StageFetchers.validate()` before anything is deployed:
  every fetcher has a `name`, every `cooldown_checks` fetcher has `is_settled()`, and a scaling one there gives
  `"running"`. Name uniqueness is not checked yet (see the architecture skill).
- **`fetchers.<name>` keys are checked per host.** `deploy` refuses a `fetchers.<name>` key that the host being
  deployed doesn't have, even if another host has it. So today one `ak-bench.yaml` with poll intervals for both
  `ecs` and `lambda` fetchers refuses both deploys (the design says "no fetcher of the selected hosts"); fix
  `Deploy.check` / `Run` to pass the names of all selected hosts before relying on a shared config.
- **Choosing the cool-down checks:** list the transport collector (queues drained) and one scaling fetcher that
  sees `running` per tier. An empty list ends the step once every request settled. A source with ingestion delay can
  still be a check (it is asked for the latest minutes); give it a delay-clipped read (see the fetcher skill).
- A fetcher that's written but not yet trusted can stay out of every list; leave a one-line comment in the bundle.

## Step 2: The deployment folder (`app/deploy/<host>-<mode>-<message-type>/`)

One folder per host × mode × message type, e.g. `ecs-async-complete/`. Without it, `deploy` is refused before
anything runs. The full contract is `benchmarks/app/deploy/README.md`; follow it exactly.

| File | Purpose |
|---|---|
| `deploy.sh` | Packages and deploys `benchmarks/app/`, then writes `$AK_BENCH_OUTPUT/deployment.json` |
| `destroy.sh` | Tears down everything `deploy.sh` created; must cope with a partial deployment and must not need `deployment.json` |
| Terraform / manifests | Reuse `ak-deployment/` modules where they fit |
| entry files | One per tier: `import agent`, then the host's entry point (Lambda `handler`, ECS `AgentRunner.run`, ...) |

Inputs (environment variables; any `AK_BENCH_*` from the caller's shell is removed first):

- `AK_BENCH_DEPLOYMENT_ID`: name every cloud resource and the Terraform state after it, so two deployments never
  collide, and tag every resource `ak-bench-run-id=$AK_BENCH_DEPLOYMENT_ID` (Terraform `default_tags` on AWS) so
  the cost fetcher can filter by it. On AWS the tag must be activated once as a cost allocation tag (#786 Cost).
- `AK_BENCH_AUTH_SECRET`: put it in the platform's secret store (AWS: SSM `SecureString`), give every component read
  access, and let the app read it through AK's secret capability. **Never** set it as an environment variable on a
  deployed component (an env var wins over the store in AK's secret resolution).
- `AK_BENCH_HOST_SETTINGS`: JSON of `host_settings.<host>` minus `max_cooldown_s`; apply the keys your host
  defines (e.g. `lambda_insights`).
- `AK_BENCH_MOCK_AGENT_MIN_DELAY_S` / `AK_BENCH_MOCK_AGENT_MAX_DELAY_S`: only with the mock agent; pass both to the
  app unchanged. Absent = real agent.
- `AK_BENCH_OUTPUT`: where `deploy.sh` writes `deployment.json`.

`deployment.json` (read by `Deployment.from_json`; all five keys required):

```json
{
  "endpoint": "wss://...",
  "resources": {"runner": {"cluster": "...", "service": "..."}, "io": {"cluster": "...", "service": "..."}},
  "queues": {"input": {"url": "..."}, "output": {"url": "..."}},
  "logs": {"runner": "/ecs/<id>/agent-runner", "io": "/ecs/<id>/io-handler"},
  "settings": {"region": "...", "tiers": {...}, "transport": "sqs", "session_store": "in_memory", "resource_usage": ..., "front_door": ...}
}
```

- `resources` keys are the **tiers**: every component that does work is its own tier. Values hold whatever ids the
  host's fetchers read; agree the keys with those fetchers.
- `logs` comes from the deployed resources (Terraform outputs), not built from tier names.
- `settings`: the #786 run-metadata fields (`region`, `tiers`, `transport`, `session_store`, `resource_usage`,
  `front_door`); a missing one is recorded as `null`.
- Scripts run as `bash <script>` from the folder, no timeout; exit 0 = done. If `deploy.sh` fails the harness runs
  `destroy.sh`; on Ctrl-C it runs nothing and a later `finish` does, with the same inputs from `state.json`.
- Keep Terraform state keyed by `AK_BENCH_DEPLOYMENT_ID`; Terraform's state lock is what stops a concurrent
  `destroy.sh`.
- Every host deploys the same app in the same shape: queue mode, `logging.ak.level: TRACE`, session store
  `in_memory`, and the #786 benchmark settings for that host. Host-specific config (transport, secret provider,
  `secret.prefix`, deployment blocks) lives in the folder, never in `app/config.yaml`.

## Step 3: Host settings (optional)

`host_settings.<host>` in `ak-bench.yaml` accepts any keys: `max_cooldown_s` overrides the step cool-down maximum
for this host, everything else goes to `deploy.sh` as JSON. Document the keys your folder reads in the #786 design
and in `benchmarks/ak-bench.example.yaml`. No harness change is needed.

## Step 4: Tests

- Registry: the new name is returned by `HostRegistry.get()` and passes `validate()`. Once `_BUILTINS` holds real
  hosts, update `tests/test_registries.py`: `test_unknown_host_with_no_builtins` asserts `(none)` and
  `test_unknown_host_lists_builtins` asserts the exact list `built-ins: mock`.
- No duplicate fetcher names in the bundle (not checked by `validate()` yet): assert it in the bundle test.
- The bundle: a test that the lists hold what the #786 Hosts table says (names per list), so a moved fetcher is a
  visible change.
- Fetchers: their own cloud-free tests (fetcher skill).
- The deployment folder is not run in CI (no cloud). Test it by hand: copy `ak-bench.example.yaml` to
  `ak-bench.yaml` (`step_run.time_window_s` and `fetchers.default.poll_interval_s` are required; keep only
  `fetchers.<name>` keys this host has, see below), then `uv run ak-bench deploy --host <h> --mode async
  --message-type complete`, one `step`, `plot`, `finish`; then check that nothing tagged with the deployment id
  is left in the account.
- `cd benchmarks && uv run pytest -q` and ruff must pass.

## Step 5: Docs

- #786 `design.md`: the host's row in the built-in bundles table, its benchmark deployment settings, and the
  research behind each fetcher choice (in `research/`, verified against official docs).
- `benchmarks/README.md`: remove "no built-in host yet" once the first host lands; add host-specific setup
  (credentials, region) if any.
- `benchmarks/app/deploy/README.md`: only if the contract itself changed (new input or output key).
- `benchmarks/ak-bench.example.yaml`: the host's `host_settings` keys and any `fetchers.<name>` poll intervals.

## Checklist

- [ ] Each family's source decided and written in the #786 design
- [ ] Missing fetchers written (fetcher skill); shared ones reused, one object each
- [ ] Bundle in `hosts/<platform>.py`, name has no `-`, merged into `HostRegistry._BUILTINS`; import is offline
- [ ] `cooldown_checks` has the transport collector and a `"running"` scaling fetcher
- [ ] Deployment folder per mode × message type: `deploy.sh` writes all five `deployment.json` keys; `destroy.sh`
      handles partial deploys; resources and Terraform state named / tagged by `AK_BENCH_DEPLOYMENT_ID`; auth secret
      only in the secret store
- [ ] Tests updated and green; one by-hand run deployed, measured and torn down cleanly
- [ ] #786 design, README and example config updated
