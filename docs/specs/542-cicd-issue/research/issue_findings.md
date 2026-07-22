# Issue #542 — CI/CD Findings

> **Historical investigation — the implemented fix took a different path.** These findings drove the
> original plan to normalize the local-wheel install across every example `deploy.sh`/`build.sh`.
> That broad per-script rewrite was **abandoned and reverted** during implementation; the shipped fix
> is centralized in `.github/scripts/run_single_test.py` (force-reinstall the branch wheel into the
> test client venv, then `uv run --no-sync pytest`), plus `fail-on-cache-miss` on the restore steps,
> the `valkey` example dependency fixes, and the opt-in `enable_api_gateway_logs` Terraform toggle.
> See [`../design.md`](../design.md) and [`../spec.md`](../spec.md) for the authoritative,
> as-built description. The per-script matrix below is retained only as background.
>
> Note also: two rows of the matrix were found inaccurate on re-verification —
> `gcp-containerized/openai` **does** carry `|| true` on its `--no-index` line (shown as "–" below),
> and `aws-serverless/scalable-openai` is **not** uniformly first-pass-`--find-links`.


**Title:** CI integration tests silently deploy PyPI `agentkernel` instead of branch build on cache miss
**Type:** Bug · **Component:** CI/CD — Integration Tests · **Priority:** High

These findings are the result of investigating the reported issue against the actual
code and empirically testing `uv`'s behavior. The core bug is **real and reproducible**,
but its mechanism is more nuanced than originally described, and its scope is **wider**.

---

## Summary

- A cache miss on `ak-py-<sha>` can silently ship PyPI's `agentkernel` and report test
  results against the wrong build. **Confirmed.**
- The single guaranteed root cause is `|| true` on the `--no-index` reinstall line, which
  defeats even `set -e`. This is compounded by the missing `fail-on-cache-miss` on the
  cache restore steps.
- The issue understates scope: a **third workflow** shares the defect, `set -e` alone is
  **insufficient**, and 6 scripts are already immune.

---

## Confirmed claims

### Claim 1 — `fail-on-cache-miss` is absent (CONFIRMED, and broader)

None of the `actions/cache/restore@v5` steps restoring `ak-py/dist` set
`fail-on-cache-miss: true`. The issue names 2 workflows (4 steps); there are actually
**3 workflows / 6 steps**:

| Workflow | Lines |
|---|---|
| `integration-test.yaml` | 87, 195 |
| `integration-test-weekly.yaml` | 93, 205 |
| **`test-reusable.yaml`** (not in the issue) | 142, 179 |

`test-reusable.yaml` restores the same `ak-py/dist` (keyed on `inputs.checkout_ref`) and
runs example deploy tests — it has the identical gap. A repo-wide grep for
`fail-on-cache-miss` returns nothing.

### Claim 3 — version equivalence (CONFIRMED)

- `ak-py/pyproject.toml` → `version = "0.6.1"`
- Examples pin `agentkernel[...]>=0.6.1`

A PyPI `0.6.1` satisfies the pin identically, so nothing downstream detects the
substitution.

### Claims 2 & 4 — `|| true` and missing `set -e` (CONFIRMED, quantified)

Of 27 `deploy.sh` scripts:

- **22** have `|| true` on the `--no-index` reinstall line.
- Only **12** have `set -e`.
- **6** self-build ak-py via `build.sh` (e.g. `azure-serverless/openai`,
  `gcp-serverless/openai-firestore`) and are therefore **cache-miss-immune** — they
  rebuild the wheel locally regardless of the cache.

The harness *does* check exit codes: `run_single_test.py` runs `./deploy.sh local` with
`check=True` (lines 228 / 377 / 529), so a nonzero `deploy.sh` fails the deploy step.
`set -e` is therefore effective **when it fires**.

---

## Key correction to the stated mechanism

Tested with `uv 0.11.21`: **`uv` errors (exit code 2) when `--find-links` points at a
missing directory** — it does *not* silently fall back to PyPI. On an
`actions/cache/restore` miss the directory is *absent* (nothing creates it;
`inject_dependencies.py` does not touch `ak-py/dist`).

| Scenario | `--no-index` pass | first pass (no `--no-index`) |
|---|---|---|
| `--find-links` dir **missing** | exit **2** | exit **2** |
| `--find-links` dir **empty** | exit **1** (no wheel) | exit **0** — resolves `agentkernel 0.6.1` **from PyPI** |

This splits the scripts into two behaviors on a full cache miss:

### Group A — first-pass install uses `--find-links` (25 scripts)

The *first* pass (`uv pip install -r requirements.txt --find-links ../../../ak-py/dist`,
no `--no-index`) itself fails with exit 2 on the missing dir.

- **With `set -e`** → aborts immediately → deploy fails **loudly** (good — though the
  error reads as a confusing "find-links" error, not "cache missing").
- **Without `set -e`** → both installs fail, artifact ships with **no `agentkernel` or
  deps at all** → noisy test crash, not a clean false-green.
- The silent PyPI green occurs here only if `ak-py/dist` exists **but is empty** (partial
  cache): first pass resolves 0.6.1 from PyPI (exit 0), `--no-index` pass fails (exit 1),
  swallowed by `|| true`.

### Group B — first-pass install has NO `--find-links` (2 scripts)

`aws-serverless/streaming-openai` and `aws-serverless/websocket-openai`. These are the
**exact, clean false-green** case, and they trigger on an ordinary full cache miss:

1. First pass installs everything **including `agentkernel 0.6.1` from PyPI** → exit 0.
2. The `--no-index` reinstall fails on the missing dir → **swallowed by `|| true`**.
3. **They have `set -e`, but it does not help** — `|| true` neutralizes the only failing
   command. `deploy.sh` exits 0, the harness reports success, and the PyPI wheel ships.

---

## Per-script matrix

| Script | `set -e` | `\|\| true` (reinstall) | first-pass `--find-links` | self-builds ak-py |
|---|:--:|:--:|:--:|:--:|
| api/multimodal/dynamodb | no | yes | yes | – |
| api/multimodal/redis | no | yes | yes | – |
| aws-containerized/adk | no | yes | yes | – |
| aws-containerized/crewai-auth | no | yes | yes | – |
| aws-containerized/crewai | no | yes | yes | – |
| aws-containerized/mcp/multi | no | yes | yes | – |
| aws-containerized/openai-dynamodb | yes | yes | yes | – |
| aws-containerized/openai-dynamodb-scalable | yes | – | yes | yes |
| aws-serverless/adk | no | yes | yes | – |
| aws-serverless/crewai | no | yes | yes | – |
| aws-serverless/langgraph | no | yes | yes | – |
| aws-serverless/openai-auth | yes | yes | yes | – |
| aws-serverless/openai | yes | yes | yes | – |
| aws-serverless/scalable-openai | yes | yes | yes | – |
| **aws-serverless/streaming-openai** | yes | yes | **NO** | – |
| **aws-serverless/websocket-openai** | yes | yes | **NO** | – |
| azure-containerized/openai-cosmos | no | – | yes | – |
| azure-serverless/openai | yes | – | yes | yes |
| gcp-containerized/openai-auth | yes | yes | yes | – |
| gcp-containerized/openai | yes | yes | yes | yes |
| gcp-serverless/openai-auth | no | yes | yes | – |
| gcp-serverless/openai | yes | yes | yes | yes |
| gcp-serverless/openai-firestore | yes | – | yes | yes |
| memory/cosmos | no | – | yes | yes |
| memory/dynamodb | no | yes | yes | – |
| memory/redis | no | yes | yes | – |
| memory/valkey | no | yes | yes | – |

Bold rows (`streaming-openai`, `websocket-openai`) are the clean silent-false-green case.

---

## Bottom line

- The core bug — *a cache miss can silently ship PyPI's `agentkernel` and report results
  against the wrong build* — is **real and reproducible**, most cleanly in
  `streaming-openai` / `websocket-openai`, and in any Group-A script if the cache is empty
  rather than absent.
- The single guaranteed root cause is `|| true` on the `--no-index` line (defeats even
  `set -e`), compounded by the missing `fail-on-cache-miss`.
- The issue understates scope three ways:
  1. A **third workflow** (`test-reusable.yaml`) shares the defect.
  2. `set -e` alone is **insufficient** while `|| true` remains — `streaming` / `websocket`
     disprove the implication that `set -e` is the fix.
  3. **6** scripts are already immune (self-build), so a blanket edit is not uniformly
     needed.
- Minor inaccuracy in the report: the cited `aws-serverless/openai/deploy/deploy.sh`
  **already has `set -e`** (line 2); its exposure is the `|| true` on line 13 plus the
  missing dir, not a missing `set -e`.
