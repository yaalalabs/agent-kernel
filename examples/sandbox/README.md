# Agent Kernel Sandbox Capability Examples

Each subfolder is a self-contained project demonstrating one aspect of the sandbox
capability. All but `identity/` (which runs over REST) and the two `broker-*` projects
(multi-process with local infrastructure; see their READMEs) are CLI projects; build and
run any of them the same way:

    cd <example>
    ./build.sh                 # or: ./build.sh local  (installs agentkernel from ../../../ak-py/dist)
    export OPENAI_API_KEY=sk-...
    uv run demo.py

In every example the agent's own instructions say nothing about the sandbox — when the
capability is enabled, Agent Kernel attaches the sandbox tools and injects the usage
guidance into the agent's system prompt automatically. Only the `config.yaml` changes
between examples.

| Example | Shows |
|---|---|
| [basic/](basic/) | The starting point: enable the sandbox, run code, persist a workspace across turns, manage named sessions. |
| [profiles/](profiles/) | Multiple named workload **profiles** with different providers and scopes; the agent routes each call to a profile. |
| [policy/](policy/) | **Policy / permissions** on the docker provider: an enforced envelope (network deny, resource limits) plus the fail-closed `strict` model for what docker cannot enforce (unenforceable policy is rejected, not silently ignored). |
| [docker/](docker/) | The **docker provider**: container-isolated execution, image configuration, package installs, and policy that is actually enforced (`network_egress: deny` → no network). Requires a Docker daemon. |
| [daytona/](daytona/) | The **daytona provider**: cloud container sandboxes with enforced network *and* resource policy (`network_block_all`, cpu/memory limits) and native idle auto-stop. Requires a Daytona API key. |
| [e2b/](e2b/) | The **e2b provider**: Firecracker micro-VM sandboxes with a **stateful** Jupyter kernel (variables persist across executions) and enforced network policy. Requires an E2B API key. |
| [identity/](identity/) | **Principal & identity**, end-to-end over REST: a multi-tenant app where sandboxed code runs under the authenticated end user's identity (custom pre-hook, principal resolver, bring-your-own provider). |
| [ec2-ssm/](ec2-ssm/) | An **attached environment** (`environment: attached`): execute code on an existing EC2 instance over SSM via the attach-only `ec2_ssm` provider. Manual only — needs a real instance and AWS credentials, so it is not in the automated e2e suite. |
| [broker-kafka/](broker-kafka/) | The **queue broker** (#503) over Kafka: a two-process split where a `QueueBrokerWorker` runs read-only kubectl pods in a kind cluster via the **kubernetes provider**, with RBAC as the security boundary, bounded waits, and `check_sandbox_task` recovery. Needs Docker, kind, and kubectl. |
| [broker-nats/](broker-nats/) | The **queue broker fully in-cluster**: pipeline plus sandbox worker deployed by the ak-k8s Helm chart over NATS, running sandbox pods in a **hardened namespace** (PSA `restricted`, default-deny egress, non-root securityContext). Walkthrough-driven (no automated suite); needs a micro-cluster. |

The `basic` example defaults to the `local_subprocess` provider so it runs with no extra
services, and `identity` uses a demo bring-your-own provider for the same reason. `policy`
and `docker` are docker-backed and need a running Docker daemon, as does `profiles`, which
routes its default `workspace` profile to the docker provider (its `scratch` profile stays
local). `daytona` and `e2b` run against their respective clouds (needs a `DAYTONA_API_KEY` /
`E2B_API_KEY`, no local daemon), and `ec2-ssm` connects to an existing EC2 instance over SSM.

> **Warning:** `local_subprocess` provides **no isolation** — the agent's code runs directly
> on your machine. It is for development and testing only. Production deployments should use
> an isolating provider (`docker`, `kubernetes`, `e2b`, or `daytona`); the `policy/`
> example explains how policy enforcement depends on the provider.
