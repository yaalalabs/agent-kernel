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
  never silently downgraded: if you asked for `network_egress: deny` and the provider can't
  guarantee it, you get an error, not a false sense of safety.
- `strict: false` → the execution proceeds, with a one-time warning naming the unenforced
  dimensions.

This example uses `local_subprocess`, which provides no isolation and therefore enforces
none of network/filesystem/resource policy — making the fail-closed behavior easy to see:

- The **`guarded`** profile (default, `strict: true`) sets `network_egress: deny` + cpu/memory
  limits. Any execution against it fails closed with a policy error.
- The **`relaxed`** profile sets the same intent with `strict: false`, so executions proceed
  and only `timeout` (always enforceable) actually applies.

Install and run:

    ./build.sh                 # or ./build.sh local
    export OPENAI_API_KEY=sk-...
    uv run demo.py

Things to try:

    Run: print("hello")                              # guarded profile -> policy error (fail closed)
    Run the same thing using the relaxed profile.    # proceeds (with a warning), prints hello

## Real enforcement

To see the same policy actually enforced instead of rejected, switch to an isolating
provider. With the `sandbox-docker` extra and a running Docker daemon, a docker-backed
profile maps the policy to real controls (`network_egress: deny` → `network_mode: none`,
`cpu`/`memory_mb` → container limits, filesystem restrictions → read-only rootfs + writable
workdir). See the commented docker profile at the bottom of `config.yaml`.

## Tests

    uv run pytest -s

The tests drive the agent (fallback comparison mode in `test-config.yaml`): one asserts the
relaxed profile computes `42`, the other that the guarded profile fails closed and the agent
reports it. Running them requires `OPENAI_API_KEY`.
