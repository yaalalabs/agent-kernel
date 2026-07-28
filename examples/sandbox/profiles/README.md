# Sandbox — Profiles

See [../README.md](../README.md) for the full set of sandbox examples.

A **profile** is a named workload configuration: a provider, a `scope`, and (in the other
examples) a policy and identity. `config.yaml` here defines two profiles that differ in both
provider and lifetime, so the agent routes each call to a genuinely different backend:

| Profile | Provider | Scope | Behavior |
|---|---|---|---|
| `workspace` (default) | `docker` | `per_session` | One container-isolated sandbox per conversation; files and state persist across turns. |
| `scratch` | `local_subprocess` | `per_call` | A brand-new local sandbox for every execution, torn down immediately after. |

The agent selects a profile per call via the `profile=` argument on the sandbox tools. Agent
Kernel renders the available profiles into the injected system prompt, so the model knows
what it can choose; `demo.py`'s instructions only describe *when* to prefer each one.

## Prerequisites

The `workspace` profile uses the docker provider (the `sandbox-docker` extra, installed by
`build.sh`) and needs a running Docker daemon; the first sandbox creation pulls
`python:3.12-slim` if it is not already present. The `scratch` profile needs no extra
services — but `local_subprocess` provides **no isolation** (development/test use only).

Install and run:

    ./build.sh                 # or ./build.sh local
    export OPENAI_API_KEY=sk-...
    uv run demo.py

Things to try:

    Create a file plan.txt with some notes.          # lands in the persistent container workspace
    What files are in my workspace?                   # plan.txt is still there
    Quickly, in a throwaway sandbox, print the Python version.   # uses the scratch profile
    Is plan.txt visible in that throwaway sandbox?    # no — scratch is a fresh local sandbox

While the CLI is running, `docker ps` on the host shows the `workspace` container; the
`scratch` executions never appear there — they run as short-lived local subprocesses.

To run tests:

    uv run pytest -s

Tests use fuzzy comparison (`test-config.yaml`) against exact values, so evaluation is
deterministic; running them requires `OPENAI_API_KEY` and (for the `workspace` profile)
a running Docker daemon.
