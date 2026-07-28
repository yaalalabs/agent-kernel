# Agent Kernel Sandbox Capability Examples

Each subfolder is a self-contained project demonstrating one aspect of the sandbox
capability. The first four are CLI projects; build and run any of them the same way:

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
| [identity/](identity/) | **Principal & identity**, end-to-end over REST: a multi-tenant app where sandboxed code runs under the authenticated end user's identity (custom pre-hook, principal resolver, bring-your-own provider). |
| [ec2-ssm/](ec2-ssm/) | An **attached environment** (`environment: attached`): execute code on an existing EC2 instance over SSM via the attach-only `ec2_ssm` provider. Manual only — needs a real instance and AWS credentials, so it is not in the automated e2e suite. |

The `basic` example defaults to the `local_subprocess` provider so it runs with no extra
services, and `identity` uses a demo bring-your-own provider for the same reason. `policy`
and `docker` are docker-backed and need a running Docker daemon, as does `profiles`, which
routes its default `workspace` profile to the docker provider (its `scratch` profile stays
local).

> **Warning:** `local_subprocess` provides **no isolation** — the agent's code runs directly
> on your machine. It is for development and testing only. Production deployments should use
> an isolating provider (`docker`, `e2b`, or `daytona` today; `kubernetes` planned); the `policy/`
> example explains how policy enforcement depends on the provider.
