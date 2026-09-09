# Sandbox — E2B Provider

See [../README.md](../README.md) for the full set of sandbox examples. This one is the
`basic` example switched to a **micro-VM** cloud provider: the `e2b` provider from the `e2b`
extra. The agent's code runs in a Firecracker micro-VM on the E2B cloud — stronger isolation
than a container, with no local daemon.

## How the provider works

Each sandbox is a Firecracker micro-VM created on E2B (native async SDK). `run_code`
executes in a **persistent Jupyter kernel**, so Python variables defined in one execution
are still bound in the next — the provider is `stateful=True`, unique among the shipped
backends (docker, daytona, and local_subprocess all reset in-memory state between calls).
`commands.run` covers shell and `pip install`, and the sandbox filesystem backs file
operations. Closing a session leaves the sandbox running so it can be reattached; destroying
the session kills it. The profile's `idle_timeout` is passed as E2B's native sandbox
`timeout`, so the platform reclaims an idle sandbox for you.

Because the provider is micro-VM-isolated in the cloud, network policy is **actually
enforced**, not merely declared ([../policy/](../policy/) explores the policy envelope and
the fail-closed `strict` model in depth):

| Policy | E2B mapping |
|---|---|
| `network_egress: deny` | `allow_internet_access: false` |
| `network_egress: allowlist` | network `allow_out` rules (only listed hosts reachable) |
| `cpu` / `memory_mb` | *not enforceable* — fixed by the E2B tier (`policy_resources=False`); a non-default value fails closed under `strict` |

The `config.yaml` defines three profiles: `default` (a per-session micro-VM workspace),
`offline` (`network_egress: deny`, so outbound requests genuinely fail), and `pinned` (an
egress allowlist E2B enforces as `allow_out` rules). Unlike `daytona`, E2B cannot enforce
cpu/memory limits (its tier fixes them), so this example does not include a resource profile.

## Prerequisites

An E2B account and API key (create one at https://e2b.dev). Export it before running:

    export E2B_API_KEY=e2b_...

(The variable name is configurable per profile via `e2b.api_key_env`; the E2B template is
configurable via `e2b.template`, default `base`.)

## Run

Install dependencies using:

    ./build.sh

Install local dependencies in development mode using:

    ./build.sh local

Set your OpenAI and E2B keys, then run the demo:

    export OPENAI_API_KEY=sk-...
    export E2B_API_KEY=e2b_...
    uv run demo.py

Things to try in the CLI:

    Run a command in the sandbox to show which OS it is running on.
    Assign x = 1729 in the sandbox, then in the next turn print x.   # persists — stateful kernel
    Compute the 30th Fibonacci number by running Python code.
    Install the requests package and print the HTTP status of https://example.com.
    Try the same fetch using the offline profile.        # fails: internet access disabled

## Tests

    uv run pytest -s

The tests require an E2B API key (`E2B_API_KEY`) and `OPENAI_API_KEY`. They use fuzzy
comparison mode (`test-config.yaml`) with sentinel replies, so every expected answer is exact
("42", "1729", "XLII", "OFFLINE") and no LLM judge is involved. Two assertions are
E2B-specific: an in-kernel variable survives across turns (the stateful signature), and the
`offline` profile's request genuinely fails inside the micro-VM.
