# Agent Kernel Sandbox Capability Examples

Each subfolder is a self-contained CLI project demonstrating one aspect of the sandbox
capability. Build and run any of them the same way:

    cd <example>
    ./build.sh                 # or: ./build.sh local  (installs agentkernel from ../../../../ak-py/dist)
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
| [policy/](policy/) | **Policy / permissions**: network egress, resource limits, and the fail-closed `strict` model (unenforceable policy is rejected, not silently ignored). |
| [docker/](docker/) | The **docker provider**: container-isolated execution, image configuration, package installs, and policy that is actually enforced (`network_egress: deny` → no network). Requires a Docker daemon. |

**Principal & identity** is a multi-tenant, request-authenticated scenario, so it lives with
the API examples: [../../api/sandbox-identity/](../../api/sandbox-identity/) runs sandboxed
code under the authenticated end user's identity end-to-end over REST.

The `basic`, `profiles`, and `policy` examples default to the `local_subprocess` provider
so they run with no extra services; `docker` needs a running Docker daemon.

> **Warning:** `local_subprocess` provides **no isolation** — the agent's code runs directly
> on your machine. It is for development and testing only. Production deployments should use
> an isolating provider (`docker` today; `e2b`, `daytona`, `kubernetes` planned); the `policy/` example
> explains how policy enforcement depends on the provider.
