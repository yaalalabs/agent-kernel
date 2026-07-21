# Sandbox — Profiles

See [../README.md](../README.md) for the full set of sandbox examples.

A **profile** is a named workload configuration: a provider, a `scope`, and (in the other
examples) a policy and identity. `config.yaml` here defines two profiles backed by the same
`local_subprocess` provider but with different lifetimes:

| Profile | Scope | Behavior |
|---|---|---|
| `workspace` (default) | `per_session` | One sandbox per conversation; files and state persist across turns. |
| `scratch` | `per_call` | A brand-new sandbox for every execution, torn down immediately after. |

The agent selects a profile per call via the `profile=` argument on the sandbox tools. Agent
Kernel renders the available profiles into the injected system prompt, so the model knows
what it can choose; `demo.py`'s instructions only describe *when* to prefer each one.

Install and run:

    ./build.sh                 # or ./build.sh local
    export OPENAI_API_KEY=sk-...
    uv run demo.py

Things to try:

    Create a file plan.txt with some notes.          # lands in the persistent workspace
    What files are in my workspace?                   # plan.txt is still there
    Quickly, in a throwaway sandbox, print the Python version.   # uses the scratch profile
    Is plan.txt visible in that throwaway sandbox?    # no — scratch is a fresh sandbox

To run tests:

    uv run pytest -s

Tests use fuzzy comparison (`test-config.yaml`) against exact values, so evaluation is
deterministic; running the agent requires `OPENAI_API_KEY`.
