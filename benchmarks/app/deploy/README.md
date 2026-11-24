# Deployment folders

One folder per host × mode × message type, named `<host>-<mode>-<message-type>/` (for example
`aws.ecs-async-complete/`). `ak-bench deploy` picks the folder and runs its scripts; the harness does not check what a
script does inside. There are none yet: they come with the host issues.

## Files

| File | Required | Purpose |
|---|---|---|
| `deploy.sh` | yes | Packages and deploys [the app](../), then writes `deployment.json` |
| `destroy.sh` | yes | Tears down everything `deploy.sh` created |
| entry files | as the host needs | One per tier: `import agent` (registers the agent), then the host's entry point (Lambda: `handler = ServerlessAgentRunner.handle`, ...; ECS: `AgentRunner.run`, `AWSWebsocketAPI.run()`) |

Both run as `bash <script>` with the folder as the working directory, stdout / stderr shown to the user, and no
timeout. A non-zero exit code is a failure. If `deploy.sh` fails, the harness runs `destroy.sh` to clean up, so
`destroy.sh` must cope with a partial deployment.

## Inputs (environment variables)

Both scripts get the same variables, on top of the caller's environment:

| Variable | Value |
|---|---|
| `AK_BENCH_DEPLOYMENT_ID` | `<run-id>-<host>-<mode>-<message-type>`; name every cloud resource and the Terraform state after it, so two deployments never collide |
| `AK_BENCH_AUTH_SECRET` | The token signing secret for this deployment. Empty for a `destroy.sh` run after a finished teardown |
| `AK_BENCH_HOST_SETTINGS` | JSON of `host_settings.<host>` from `ak-bench.yaml`, `{}` when absent |
| `AK_BENCH_OUTPUT` | The deployment's results directory; `deploy.sh` writes `deployment.json` here |
| `AK_BENCH_MOCK_AGENT_MIN_DELAY_S` / `AK_BENCH_MOCK_AGENT_MAX_DELAY_S` | Only with the mock agent; pass both to the app unchanged |

## Output: `$AK_BENCH_OUTPUT/deployment.json`

Written by `deploy.sh` on success. A missing or unreadable file is a failure.

| Field | Meaning |
|---|---|
| `endpoint` | The URL clients connect to |
| `resources` | What the host's fetchers read for scaling and resource usage (service / cluster names, ...) |
| `queues` | The transport's queues, for the transport collector |
| `logs` | Where the app's `TRACE` lines are written, for the trace collector |
| `settings` | Host settings as deployed, recorded in the run metadata |

## Rules

- **Terraform state per deployment id.** Keep state keyed by `AK_BENCH_DEPLOYMENT_ID` so `destroy.sh` removes exactly
  what its `deploy.sh` created.
- **The auth secret goes into the cloud's secret store, never onto a component's environment.** Store
  `AK_BENCH_AUTH_SECRET` in the host's secret store (on AWS: SSM, with `secret.provider.type: aws_ssm` in the app's
  config) and let the app resolve it from there. **No component may set an `AK_BENCH_AUTH_SECRET` environment
  variable**: an environment variable wins over the store in Agent Kernel's secret resolution, so it would bypass the
  store.
- **Host-specific config belongs to the folder.** Transport, secret provider, `secret.prefix` and deployment blocks
  are set here (environment variables or the folder's own config), not in the app's `config.yaml`.
