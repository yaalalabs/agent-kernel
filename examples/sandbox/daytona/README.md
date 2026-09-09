# Sandbox — Daytona Provider

See [../README.md](../README.md) for the full set of sandbox examples. This one is the
`basic` example switched to a **cloud** isolating provider: the `daytona` provider from the
`daytona` extra. The agent's code runs in a container on the Daytona platform, not on your
machine and with no local daemon.

## How the provider works

Each sandbox is a container created on the Daytona cloud. Executions run via
`process.code_run` / `process.exec`, files travel through the sandbox filesystem, and
`install_packages` is a `pip install` run in the sandbox. The synchronous Daytona SDK is
driven off the event loop (every call in `asyncio.to_thread`). Closing a session leaves the
sandbox running so it can be reattached later; destroying the session deletes it. The
profile's `idle_timeout` maps onto Daytona's native `auto_stop_interval` (minutes, rounded
up), so the platform reclaims an idle sandbox for you.

The sandbox base is configurable on the `daytona` block: `image` (a container image),
`snapshot` (a named Daytona snapshot; mutually exclusive with `image` — omit both for
Daytona's default), and `env_vars` (environment variables set inside the sandbox). The
`default` profile in `config.yaml` sets `image: python:3.12-slim` and an `APP_ENV` var to
show this.

Because the provider is container-isolated in the cloud, policy is **actually enforced**,
not merely declared ([../policy/](../policy/) explores the policy envelope and the
fail-closed `strict` model in depth):

| Policy | Daytona mapping |
|---|---|
| `network_egress: deny` | `network_block_all` |
| `network_egress: allowlist` | `network_allow_list` (CIDRs) |
| `cpu` / `memory_mb` | container `Resources` (image-based sandbox) |

The `config.yaml` defines three profiles: `default` (a per-session cloud workspace on an
explicit image), `offline` (`network_egress: deny`, so outbound requests genuinely fail),
and `small` (cpu/memory limits Daytona enforces on the container). This is a richer
enforcement set than `docker`, which cannot map resource limits as cleanly. Note: resource
limits require an image-based sandbox, so a `small`-style profile cannot also pin a
`snapshot` (Agent Kernel rejects that combination at creation).

## Prerequisites

A Daytona account and API key (create one at https://app.daytona.io). Export it before
running:

    export DAYTONA_API_KEY=dtn_...

(The variable name is configurable per profile via `daytona.api_key_env`.)

## Run

Install dependencies using:

    ./build.sh

Install local dependencies in development mode using:

    ./build.sh local

Set your OpenAI and Daytona keys, then run the demo:

    export OPENAI_API_KEY=sk-...
    export DAYTONA_API_KEY=dtn_...
    uv run demo.py

Things to try in the CLI:

    Run a command in the sandbox to show which OS it is running on.
    Compute the 30th Fibonacci number by running Python code.
    Write a file called notes.txt containing "hello", then read it back.
    Install the requests package and print the HTTP status of https://example.com.
    Try the same fetch using the offline profile.        # fails: network blocked in that sandbox
    Start a fresh sandbox session named "experiment" and initialize a uv project in it.

## Tests

    uv run pytest -s

The tests require a Daytona API key (`DAYTONA_API_KEY`) and `OPENAI_API_KEY`. They use fuzzy
comparison mode (`test-config.yaml`): the sandbox executes real code and the prompts pin
sentinel replies, so every expected answer is exact ("42", "hello sandbox", "XLII",
"OFFLINE") and no LLM judge is involved. The network test asserts the enforced side of the
policy story: the `offline` profile's request genuinely fails inside the sandbox.
