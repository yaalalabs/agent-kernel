# Sandbox — Policy & Permissions

See [../README.md](../README.md) for the full set of sandbox examples.

A profile's `policy` block is the permission and resource envelope an execution runs within:

| Field | Meaning |
|---|---|
| `network_egress` | `allow` (default), `deny`, or `allowlist` (with `network_allow`). |
| `network_allow` | Domains/CIDRs permitted when `network_egress: allowlist`. |
| `fs_allow_read` / `fs_allow_write` | Filesystem paths the sandbox may read / write. |
| `cpu` / `memory_mb` | Resource limits. |
| `timeout` | Per-execution wall-clock limit (seconds); always enforced framework-side. |
| `strict` | Fail closed when a dimension can't be enforced (default `true`). |

## Enforcement is per-provider, and unenforceable ≠ ignored

Every provider declares which policy dimensions it can actually enforce. When a profile sets
a non-default dimension the provider **cannot** enforce, the `strict` flag decides what happens:

- `strict: true` (default) → the execution is **rejected** with a policy error. Security is
  never silently downgraded: if you asked for a restriction the provider can't guarantee,
  you get an error, not a false sense of safety.
- `strict: false` → the execution proceeds, with a warning naming the unenforced dimensions.

This example is docker-backed, which shows **both sides** of that model:

- The **`guarded`** profile (default) sets `network_egress: deny` plus cpu/memory limits.
  docker maps every dimension to a real control (`deny` → `network_mode: none`,
  `cpu`/`memory_mb` → container limits), so executions **run with the policy enforced**:
  code works normally, but network access genuinely fails inside the container.
- The **`restricted`** profile sets a network egress **allowlist**, the one network mode
  docker cannot enforce. With `strict: true`, every execution against it **fails closed**
  with a policy error.
- The **`relaxed`** profile sets the same allowlist with `strict: false`, so executions
  proceed with a warning and egress is effectively unrestricted. The explicit opt-out.

(On a provider that enforces nothing, like `local_subprocess`, the same `guarded` profile
would fail closed too: the `strict` model is uniform, only each provider's enforceable set
changes.)

## Prerequisites

A running Docker daemon; `build.sh` installs the `sandbox-docker` extra. The first sandbox
creation pulls `python:3.12-slim` if it is not already present.

## Run

    ./build.sh                 # or ./build.sh local
    export OPENAI_API_KEY=sk-...
    uv run demo.py

Things to try:

    Run: print("hello")                                       # guarded -> runs, policy enforced
    Fetch https://example.com and print the status code.      # guarded -> fails: egress denied
    Run print("hello") using the restricted profile.          # rejected: allowlist unenforceable (fail closed)
    Run print("hello") using the relaxed profile.             # proceeds, with a warning

For the docker provider itself (images, package installs, reattach behavior), see
[../docker/](../docker/).

## Tests

    uv run pytest -s

The tests require a running Docker daemon and `OPENAI_API_KEY`. They use fuzzy comparison
mode (`test-config.yaml`) with sentinel replies, so every expected answer is exact: the
guarded profile computes `42` but reports `OFFLINE` for a network fetch (deny enforced),
the restricted profile reports `BLOCKED` (fail closed), and the relaxed profile computes
`42` (strict opt-out proceeds).
