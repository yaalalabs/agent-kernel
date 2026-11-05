# Sandbox — Docker Provider

See [../README.md](../README.md) for the full set of sandbox examples. This one is the
`basic` example switched to a **real isolating provider**: the `docker` provider from the
`sandbox-docker` extra. The agent's code runs inside a container, not on your machine.

## How the provider works

Each sandbox is its own container, created from the configured `image` (default
`python:3.12-slim`) and kept alive with `sleep infinity`. Executions are `exec` calls
inside it (`run_code` execs the interpreter `docker.language_runtimes` names for the language,
default `python -c`; the `default` profile here adds `bash: [bash, -c]`, so `run_code` also takes
`bash` code; see [Language runtimes](https://kernel.yaala.ai/docs/advanced/sandbox#language-runtimes)), files live under `/workspace`, and `install_packages` runs the installer configured in
`docker.package_installers` (default `pip install`) in the container, on a profile whose policy
permits it (`policy.package_install`; installs are denied by default). Closing a session leaves the container running so the sandbox can be
reattached later; destroying the session force-removes it. An idle-expired sandbox
(`idle_timeout`, 6 hours here) is removed and transparently recreated on next use with an
empty workspace, and the agent is told via a result "notice" when that happens.

Because the provider is container-isolated, policy is **actually enforced**, not merely
declared ([../policy/](../policy/) explores the policy envelope and the fail-closed
`strict` model in depth):

| Policy | Docker mapping |
|---|---|
| `network_egress: deny` | `network_mode: none` |
| `cpu` / `memory_mb` | container cpu/memory limits |
| `fs_allow_read` / `fs_allow_write` | read-only rootfs + writable tmpfs workdir |

The `config.yaml` defines two profiles: `default` (a per-session container workspace that
permits `python` package installs and runs `python` or `bash` code through `language_runtimes`) and `offline` (`network_egress: deny`, so network access
genuinely fails inside the container, and no package installs). An egress *allowlist* is the one network mode docker cannot enforce; under
`strict: true` (the default) such a profile is rejected rather than silently downgraded.

## Prerequisites

A running Docker daemon (Docker Desktop, Colima, ...). The first sandbox creation pulls
`python:3.12-slim` if it is not already present, so the first execution can take a moment;
`docker pull python:3.12-slim` ahead of time avoids that.

## Run

Install dependencies using:

    ./build.sh

Install local dependencies in development mode using:

    ./build.sh local

Set your OpenAI API key, then run the demo:

    export OPENAI_API_KEY=sk-...
    uv run demo.py

Things to try in the CLI:

    Run a command in the sandbox to show which OS and hostname it is running on.
    Compute the 30th Fibonacci number by running Python code.
    Run bash code (language bash) that prints the shell's version.
    Write a file called notes.txt containing "hello", then read it back.
    Install the requests package and print the HTTP status of https://example.com.
    Try the same fetch using the offline profile.        # fails: no network in that container
    Start a fresh sandbox session named "experiment" and initialize a uv project in it.

While the CLI is running, `docker ps` on the host shows the sandbox containers (one per
active session); destroying a session or letting it idle out removes its container.

## Tests

    uv run pytest -s

The tests require a running Docker daemon and `OPENAI_API_KEY`. They use fuzzy comparison
mode (`test-config.yaml`): the sandbox executes real code and the prompts pin sentinel
replies, so every expected answer is exact ("42", "hello sandbox", "XLII", "OFFLINE",
"BASH OK") and
no LLM judge is involved. The network test asserts the enforced side of the policy story:
the `offline` profile's request genuinely fails inside the container.
