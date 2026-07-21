# #542: Fail loudly when integration tests can't use the branch-built agentkernel wheel — Implementation Spec

This spec details how the design in [`design.md`](./design.md) is built. The change is confined to
CI/CD assets — no `ak-py` source, `AKConfig`, factory, or public-API changes — across three
surfaces: six `actions/cache/restore@v5` steps in three workflows (Guard 1); the `agentkernel`
local-wheel install block in the example `deploy/deploy.sh` scripts (Guard 2a); and the same
force-reinstall line in the example `build.sh` scripts that populate the **test** virtualenv
(Guard 2b). The design idea is unchanged: independent guards, any one of which alone prevents a
wrong-build test run — fail the cache restore on a miss, and make every local-wheel install exit
non-zero (never swallowed by `|| true`) when it fails. `design.md` is the requirements source;
every requirement there is traced to a section here.

> **Scope note.** The `build.sh` surface (Guard 2b) was added after the original spec: the
> `memory` / `api` / `cli` / `containerized` integration tests run `./build.sh local` + `uv run
> pytest` (never `deploy.sh`), and `build.sh` carried the identical `|| true` anti-pattern — so a
> cache-missed local wheel silently left the PyPI `agentkernel` in the test venv (observed as a
> `session.type: valkey` `ValidationError`, since PyPI `0.6.1` predates `valkey` support).

All per-script facts below were re-verified mechanically against the base branch
(`bugfix/542-cicd`) at spec-writing time and **supersede the per-script matrix in
[`research/issue_findings.md`](./research/issue_findings.md)**, which has two confirmed errors (see
[Corrections to the research matrix](#corrections-to-the-research-matrix)).

## Design

### Guard 1 — `fail-on-cache-miss` on the restore steps

`actions/cache/restore@v5` accepts a `fail-on-cache-miss` input; when `true` the step fails
immediately on a cache miss instead of continuing with the `path` absent. Add it to all six restore
steps that restore `ak-py/dist`. Each restore step currently reads:

```yaml
      - name: Restore ak-py build
        uses: actions/cache/restore@v5
        with:
          path: ak-py/dist
          key: ak-py-${{ github.sha }}          # or ${{ inputs.checkout_ref }} in test-reusable
```

Add one line inside each `with:` block:

```yaml
        with:
          path: ak-py/dist
          key: ak-py-${{ github.sha }}
          fail-on-cache-miss: true
```

Exact locations (step's `uses:` line → the restore step; insert after the `key:` line):

| Workflow | Restore steps (`uses:` line) | `key:` line to insert after |
|---|---|---|
| `.github/workflows/integration-test.yaml` | 87, 195 | 90, 198 |
| `.github/workflows/integration-test-weekly.yaml` | 93, 205 | 96, 208 |
| `.github/workflows/test-reusable.yaml` | 142, 179 | 145, 182 |

The three `actions/cache/save@v5` steps in the `build-ak-py` / `Build ak-py` jobs
(`integration-test.yaml:62`, `integration-test-weekly.yaml:68`, `test-reusable.yaml:87`) are
**not** changed — `fail-on-cache-miss` is a restore-only input and saving must still succeed on a
first build.

### Guard 2a — `deploy.sh` fails when the local wheel can't be installed

#### Canonical failure contract

Every `deploy.sh` invoked with `local` must satisfy two properties so a failed local-wheel install
propagates a non-zero exit up to `run_single_test.py`:

1. **`set -e` is active** before the first install command. Scripts that already set a stricter
   variant (`set -eo pipefail`, `set -euo pipefail`) keep it — `set -e` is the minimum, not a
   rewrite target.
2. **No `--no-index` install line ends with `|| true`.** `|| true` forces a zero exit even under
   `set -e`, so it is the single guaranteed defeater and must be removed from every occurrence.

Under full normalization (design open-question 1, resolved to *full normalization*), the
`--no-index` reinstall line is also brought to one shape, matching the reference
`examples/azure-serverless/openai/deploy/deploy.sh:14`:

```bash
uv pip install --force-reinstall --no-deps --no-index --target=<TARGET> \
  --find-links <REL>/ak-py/dist agentkernel[<EXTRAS>] --no-cache-dir
```

Normalization rules — apply per install target, changing only failure-behavior tokens:

1. Remove a trailing `|| true` if present.
2. Add `--no-cache-dir` if absent (idempotent install output; avoids a stale uv cache masking a
   bad wheel).
3. **Preserve verbatim**, per script: the `--target=<TARGET>` value, the `--find-links` relative
   path (`../../../ak-py/dist` for two-directory examples, `../../../../ak-py/dist` for
   three-directory examples such as `api/multimodal/*` and `aws-containerized/mcp/multi`), and the
   `agentkernel[<EXTRAS>]` extras set. These are not part of the bug and must not change.
4. **Do not change a target's pass structure** (see the Group-B decision below): a target that is
   two-pass (a `-r requirements.txt … --find-links` deps pass followed by a `--no-index` pass)
   stays two-pass; a target that is single-pass `--no-deps --no-index` stays single-pass. The
   canonical *contract* is uniform failure behaviour, not a uniform number of passes — forcing a
   synthetic deps pass onto the intentionally `--no-deps`-only targets would change what those
   Lambda artifacts ship, which is out of scope for #542.

#### Group-B decision (resolves design open-question 4, and supersedes review suggestion 3)

The design's Group B (targets whose local branch has no first-pass `--find-links`) is wider than
the two scripts named in `research/issue_findings.md`. Verified single-pass `--no-deps --no-index`
targets:

- `aws-serverless/streaming-openai` — all 4 handler targets.
- `aws-serverless/websocket-openai` — all 4 handler targets.
- `aws-serverless/scalable-openai` — the request-handler (`:39`) and response-handler (`:73`)
  targets; its agent-runner target (`:56`–`:57`) is two-pass.
- `aws-serverless/openai-auth` — the auxiliary auth-lambda target (`:33`, already without
  `|| true`).

For these, closing the bug does **not** require adding a deps pass: with `|| true` gone and `set -e`
present, the `--no-index` pass exits non-zero on a cache miss (uv exit `2` on a missing
`--find-links` directory, exit `1` on an empty one) and aborts the script. This is design
open-question 4's "rely solely on the un-swallowed `--no-index` pass" branch. My earlier review
suggestion to add a first-pass deps install to `streaming`/`websocket` is **withdrawn** on the
evidence that those targets are `--no-deps`-only by construction — synthesizing a deps pass would
alter their shipped contents. See [pre-existing observation](#pre-existing-observation-out-of-scope).

#### Per-script change classification

All 27 `deploy.sh` scripts, with the verified attributes and the exact edit each needs. "Self-build"
scripts run `./build.sh local` inside `deploy.sh` and are cache-miss-immune; their `build.sh`
invocation is never touched (design non-goal), but a stray `|| true` on their install line is still
removed because it is the same anti-pattern and is counted among the 22 (design Requirements →
Guard 2 scope).

| # | Script (`examples/…/deploy/deploy.sh`) | `set -e`? | `\|\| true`? | self-build? | Edit |
|---|---|:--:|:--:|:--:|---|
| 1 | `api/multimodal/dynamodb` | – | yes | – | add `set -e`; remove `\|\| true`; add `--no-cache-dir` |
| 2 | `api/multimodal/redis` | – | yes | – | add `set -e`; remove `\|\| true`; add `--no-cache-dir` |
| 3 | `aws-containerized/adk` | – | yes | – | add `set -e`; remove `\|\| true`; add `--no-cache-dir` |
| 4 | `aws-containerized/crewai-auth` | – | yes | – | add `set -e`; remove `\|\| true`; add `--no-cache-dir` |
| 5 | `aws-containerized/crewai` | – | yes | – | add `set -e`; remove `\|\| true`; add `--no-cache-dir` |
| 6 | `aws-containerized/mcp/multi` | – | yes | – | add `set -e`; remove `\|\| true`; add `--no-cache-dir` |
| 7 | `aws-serverless/adk` | – | yes | – | add `set -e`; remove `\|\| true`; add `--no-cache-dir` |
| 8 | `aws-serverless/crewai` | – | yes | – | add `set -e`; remove `\|\| true`; add `--no-cache-dir` |
| 9 | `aws-serverless/langgraph` | – | yes | – | add `set -e`; remove `\|\| true`; add `--no-cache-dir` |
| 10 | `gcp-serverless/openai-auth` | – | yes | – | add `set -e`; remove `\|\| true`; add `--no-cache-dir` |
| 11 | `memory/dynamodb` | – | yes | – | add `set -e`; remove `\|\| true`; add `--no-cache-dir` |
| 12 | `memory/redis` | – | yes | – | add `set -e`; remove `\|\| true`; add `--no-cache-dir` |
| 13 | `memory/valkey` | – | yes | – | add `set -e`; remove `\|\| true`; add `--no-cache-dir` |
| 14 | `azure-containerized/openai-cosmos` | – | – | – | add `set -e`; add `--no-cache-dir` |
| 15 | `aws-containerized/openai-dynamodb` | yes | yes | – | remove `\|\| true`; add `--no-cache-dir` |
| 16 | `aws-serverless/openai-auth` | yes | yes (×1, `:15`) | – | remove `\|\| true` (`:15`); add `--no-cache-dir` (`:15`, `:33`) |
| 17 | `aws-serverless/openai` | yes | yes | – | remove `\|\| true`; add `--no-cache-dir` |
| 18 | `aws-serverless/scalable-openai` | yes (`-eo pipefail`) | yes (×3) | – | remove `\|\| true` (`:39`,`:57`,`:73`); add `--no-cache-dir` (×3) |
| 19 | `aws-serverless/streaming-openai` | yes | yes (×4) | – | remove `\|\| true` (×4); add `--no-cache-dir` (×4) |
| 20 | `aws-serverless/websocket-openai` | yes | yes (×4) | – | remove `\|\| true` (×4); add `--no-cache-dir` (×4) |
| 21 | `gcp-containerized/openai-auth` | yes (`-euo pipefail`) | yes | – | remove `\|\| true`; add `--no-cache-dir` |
| 22 | `gcp-containerized/openai` | yes | **yes** | yes | remove `\|\| true`; add `--no-cache-dir` (do **not** touch `build.sh`) |
| 23 | `gcp-serverless/openai` | yes | yes | yes | remove `\|\| true`; add `--no-cache-dir` (do **not** touch `build.sh`) |
| 24 | `memory/cosmos` | – | – | yes | add `set -e` (immune; consistency only — do **not** touch `build.sh`) |
| 25 | `aws-containerized/openai-dynamodb-scalable` | yes | – | yes | none (immune; shape divergence tracked separately) |
| 26 | `azure-serverless/openai` | yes | – | yes | none (reference shape) |
| 27 | `gcp-serverless/openai-firestore` | yes | – | yes | none |

Tallies (each verified by enumeration): **22** scripts carry `|| true` on a `--no-index` line
(#1–13, #15–23) → all removed; **15** lack `set -e` (#1–14, #24) → all gained it; **6** self-build
(#22–27); **3** need no edit (#25–27).

### Guard 2b — example `build.sh` fails when the local wheel can't be installed

Each example `build.sh local` sets up the venv the tests actually run in. Its `local` branch is:

```bash
uv sync --find-links ../../../ak-py/dist --all-extras                                  # installs agentkernel 0.6.1 FROM PyPI (uv.lock pin)
uv pip install --force-reinstall --no-deps --no-index --find-links ../../../ak-py/dist agentkernel[<EXTRAS>] || true   # the ONLY line that swaps in the branch wheel
```

`uv sync` resolves `agentkernel` from PyPI because `uv.lock` records
`source = { registry = "https://pypi.org/simple" }` (e.g. `examples/memory/valkey/uv.lock:20`);
the `--find-links` flag does not override that pin. The force-reinstall line is therefore the sole
mechanism that installs the branch wheel.

**Two independent defects on that one line — both must be fixed (both verified by reproduction):**

1. **`|| true` swallows a hard failure.** On a cache miss (`ak-py/dist` empty/absent) the
   `--no-index` install exits non-zero; `|| true` forces exit 0, leaving PyPI's `agentkernel` in
   the venv. → **Remove `|| true`.**
2. **The uv package cache serves a stale same-version wheel.** Even with `ak-py/dist` present and
   containing the correct branch wheel, `uv pip install --force-reinstall --no-index --find-links`
   *without* `--no-cache-dir` installs a **cached** `agentkernel 0.6.1` (the copy uv downloaded
   from PyPI during `uv sync`) rather than the wheel in `--find-links`, because they share the
   version string. The install reports success while shipping the wrong wheel. Verified: the same
   force-reinstall installs the `valkey`-supporting config only with `--no-cache-dir`, and only the
   PyPI (no-`valkey`) config without it. → **Add `--no-cache-dir`.** This is the *primary* fix for
   the observed `valkey` failure; `|| true` removal alone does not close it.

**Failure contract:**

1. **`set -e` is already active.** All 64 example `build.sh` set `set -euo pipefail` at the top —
   no additions needed (enumerated: zero `build.sh` lack it).
2. **Remove `|| true`** and **add `--no-cache-dir`** to the force-reinstall local-wheel line.
3. **`uv run pytest` does not undo it.** `run_simple_test` runs `uv run pytest` after
   `build.sh local`; `uv run` re-syncs the project env but leaves the force-reinstalled wheel in
   place because it is still `version 0.6.1` and satisfies the lock (verified end-to-end,
   `uv 0.11.21`: after `build.sh local` the venv's `config.py` contains `valkey`, and it still does
   after `uv run`). So no `--no-sync`, `[tool.uv.sources]`, or lockfile change is required (design
   non-goal). *(Caveat: a stray `VIRTUAL_ENV` in the shell redirects `uv pip install` to that env
   instead of the project `.venv`; CI does not set it, and it is not part of this change.)*

**Scope.** 64 example `build.sh` each have a force-reinstall local-wheel line, and each is edited to
end in `--no-cache-dir` with no `|| true`:
- **`|| true` removal:** 62 lines across **61** files carried it → all removed.
  `examples/containerized/openai/build.sh` has two force-reinstall lines (both fixed); the 3
  `build.sh` whose line already lacked `|| true` keep that. The unrelated `rm -rf dist || true` in
  `containerized/openai` is intentional cleanup and left as-is.
- **`--no-cache-dir` addition:** appended to every force-reinstall line that lacked it (all 64
  scripts / 65 lines now carry it).
- Five force-reinstall lines use `--find-links` **without** `--no-index`
  (`cli/openai_structured:15`, `api/openai_structured:15`, `api/thread-openai:15`,
  `api/multimodal/thread-openai:15`, `aws-containerized/openai-dynamodb-scalable:15`). They still
  get `|| true` removed and `--no-cache-dir` added; tightening to `--no-index` is out of scope
  (design open question — it changes resolution behaviour).

### Consumer — `run_single_test.py` (verified unchanged)

No change. `run_command` (`:24`–`:50`) runs every subprocess with `check=True`, catches
`subprocess.CalledProcessError`, prints `❌ Failed`, and returns `False`, failing the step. Two
call paths rely on this — both already correct; the scripts simply never returned non-zero:

- **Guard 2a:** `./deploy.sh local` at `:228`, `:377`, `:529` (deploy/destroy actions).
- **Guard 2b:** `run_simple_test` (`:84`–`:110`) runs `./build.sh local` at `:97`; on success it
  runs `uv run pytest …` at `:105` in the venv `build.sh` populated. Dispatched for the `memory`,
  `api`, `cli`, and `containerized` types (`:621`–`:628`). Once `build.sh` stops swallowing the
  install failure, a cache-missed wheel makes `:97` return non-zero and pytest never runs against
  the wrong build.

Verified present and unchanged; listed here so a reviewer confirms both guards have a live
consumer.

### Config changes

None. No `AKConfig` field, YAML key, `AK_*` env var, `pyproject.toml` version, `agentkernel` pin, or
extras set changes (all design non-goals).

### Behavioural changes

Exhaustive; each is intended.

1. **Cache miss now fails the deploy job at the restore step.** Previously a missing/evicted
   `ak-py-<sha>` (or `ak-py-<checkout_ref>`) entry let the job continue with `ak-py/dist` absent;
   now the `Restore ak-py build` step fails immediately in all three workflows. *Justification:* the
   core of #542 — no job may test against an absent branch wheel.
2. **A failed `--no-index` local-wheel install now aborts `deploy.sh` before `terraform
   apply`.** Removing `|| true` plus guaranteeing `set -e` makes the non-zero uv exit propagate;
   `run_single_test.py` then fails the deploy step. *Justification:* Guard 2 — no run may report
   results against a PyPI-sourced `agentkernel`.
3. **Scripts that previously continued past a failed install (no `set -e`) now abort.** Applies to
   the 15 scripts that gained `set -e`. Their first-pass `-r requirements.txt … --find-links` install
   (Group A) already fails on a missing dir; with `set -e` that failure now stops the script instead
   of proceeding to build a broken artifact. *Justification:* Guard 2 defense-in-depth.
4. **`--no-cache-dir` added to every normalized `deploy.sh` `--no-index` line.** A stale uv cache
   can no longer supply an `agentkernel` wheel when `--find-links` is empty/missing.
   *Justification:* consistency with the reference shape and closes a residual "cache present but
   dir empty" corner.
5. **`build.sh local` now installs the branch wheel into the test venv instead of PyPI's.** Both
   `|| true` (swallowed cache-miss failure) and the missing `--no-cache-dir` (uv serving a cached
   same-version `0.6.1`) are fixed on the force-reinstall line of all 64 example `build.sh`.
   *Justification:* Guard 2b — the `memory`/`api`/`cli`/`containerized` tests run against
   `build.sh`'s venv, and this is the defect behind the observed `session.type: valkey`
   `ValidationError`.
6. **A failed local-wheel install in `build.sh` now aborts before `uv run pytest`.** With `|| true`
   gone and `set -euo pipefail` already active, a cache-missed wheel makes `build.sh` exit
   non-zero; `run_single_test.py` fails the test step instead of running pytest against PyPI's
   `agentkernel`. *Justification:* Guard 2b defense-in-depth.

**Non-changes** (explicitly fixed): the cache `save` steps and cache keys; each script's
`--target`, `--find-links` path, and `agentkernel[…]` extras; the pass structure of every install
target (two-pass stays two-pass, single-pass stays single-pass); the six self-builders' `build.sh
local` invocations inside `deploy.sh`; `build.sh`'s `uv sync`/`uv venv` lines, its `uv.lock`, and
example `pyproject.toml` (no `[tool.uv.sources]`, no `--no-sync`); the benign `rm -rf dist || true`;
`terraform init` / `terraform apply` lines; `run_single_test.py`; all `config.yaml`,
`requirements.txt` generation, and Dockerfiles.

### Pre-existing observations (out of scope)

1. In `streaming-openai` and `websocket-openai`, the `local` branch of every handler target installs
   `agentkernel[...] --no-deps --no-index` **only**, with no `-r requirements.txt` pass — so those
   local artifacts appear to ship without their non-`agentkernel` dependencies, independent of #542.
   This spec does **not** change it (doing so would alter shipped contents and exceeds the issue's
   scope). Flagged for a separate issue.
2. Once Guard 2b lets the `memory/valkey` test import the correct `agentkernel`, collection fails on
   a **different** error: `ragas` imports `from langchain_community.chat_models.vertexai import
   ChatVertexAI` (`.../ragas/llms/base.py:12`), which no longer exists in the resolved
   `langchain-community` → `ModuleNotFoundError`. This is a `ragas`/`langchain-community` version
   incompatibility in the `test` extra, unrelated to #542 and masked until now by the `agentkernel`
   substitution. Out of scope here; needs its own dependency fix (pin/upgrade in `ak-py`'s `test`
   extra or `ragas`). Noted so it is not mistaken for a regression from this change.

## Error handling

- **Cache miss (Guard 1):** `actions/cache/restore@v5` with `fail-on-cache-miss: true` exits the
  step non-zero; GitHub Actions fails the job. No `deploy.sh` runs.
- **Local wheel unavailable at install time (Guard 2), `--find-links` dir missing:** uv exits `2`;
  under `set -e` (and no `|| true`) the script aborts. For two-pass targets this fires on the
  first-pass `-r requirements.txt … --find-links` install; for single-pass targets on the
  `--no-index` line. Either way, before `terraform apply`.
- **`--find-links` dir present but empty (partial cache):** the `--no-index` pass exits `1`; with
  `|| true` removed and `set -e` active, the script aborts. This is the case `set -e` alone could
  not catch while `|| true` remained.
- **Error message clarity:** the surfaced failure reads as a uv `--find-links`/`--no-index`
  resolution error, not "cache missing". Acceptable — Guard 1 already names the cache miss at the
  restore step; Guard 2 is the backstop. No custom error text is added (design open-question 2 —
  provenance assertion — is deferred).
- **`build.sh` (Guard 2b):** on a cache miss the un-swallowed `--no-index` force-reinstall exits
  non-zero and `set -euo pipefail` aborts `build.sh` before `uv run pytest`. With `ak-py/dist`
  present, `--no-cache-dir` guarantees the branch wheel from `--find-links` is installed rather than
  a cached PyPI `0.6.1`.

## Testing

There is no `pytest` surface for shell scripts or workflow YAML (`ak-py/tests/` covers the Python
package only), so verification is static assertions plus an optional CI dry-run, not unit tests.

**Static acceptance checks (must pass after the change):**

1. No swallowed local install remains in **either** script family:
   ```bash
   grep -rn "no-index" examples --include=deploy.sh | grep "|| true"   # expect: no output
   grep -rn "force-reinstall" examples --include=build.sh | grep "|| true"   # expect: no output
   ```
2. Every script that force-reinstalls the local wheel has `set -e` active. For `deploy.sh`,
   enumerate the 24 in-scope scripts (all except the three no-edit self-builders #25–27, which
   already have it) and assert an `set -e[a-z]*` line precedes the first `uv pip install`; all 64
   `build.sh` already carry `set -euo pipefail`.
3. Every `build.sh` force-reinstall line carries `--no-cache-dir`:
   ```bash
   grep -rn "force-reinstall" examples --include=build.sh | grep -v "no-cache-dir"   # expect: no output
   ```
4. `fail-on-cache-miss: true` present on all six restore steps and absent from the three save steps:
   ```bash
   grep -rn "fail-on-cache-miss" .github/workflows/{integration-test,integration-test-weekly,test-reusable}.yaml  # expect: 6 hits
   ```

**Dynamic check (scoped, no cloud credentials):** for a representative script from each shape —
Group A two-pass (e.g. `memory/redis`), single-pass `--no-deps` (e.g. `streaming-openai`), and a
self-builder left unchanged (e.g. `azure-serverless/openai`) — run `./deploy.sh local` with
`ak-py/dist` (a) absent and (b) present-but-empty, using a PATH-stubbed `terraform` that records
invocation. Assert: exit code non-zero, and the `terraform` stub was **not** invoked, for the two
cache-dependent scripts; the self-builder still succeeds (it rebuilds the wheel). This proves Guard
2a aborts before `terraform apply`.

**Dynamic check — `build.sh` (Guard 2b), performed and passing:** with `VIRTUAL_ENV` unset (as in
CI), rebuild `ak-py` (`cd ak-py && ./build.sh`) so `ak-py/dist` holds the current branch wheel, then
in `examples/memory/valkey` run `rm -rf .venv && ./build.sh local` followed by `uv run pytest --co`.
Assert the installed `.venv/.../agentkernel/core/config.py` `session.type` pattern **includes
`valkey`** (i.e. the branch wheel, not PyPI `0.6.1`) both immediately after `build.sh` and after
`uv run`. Verified: the `session.type: valkey` `ValidationError` no longer occurs. *(A separate,
pre-existing failure surfaces afterward — `ragas` importing
`langchain_community.chat_models.vertexai`, a ragas/langchain-community version incompatibility —
which is unrelated to #542 and out of scope; see below.)*

**Optional CI dry-run (manual):** delete the `ak-py-<sha>` cache entry for a commit and dispatch
`integration-test-weekly.yaml`; confirm the deploy job fails at `Restore ak-py build` (Guard 1).

**Optional regression guard (recommended; design non-goal, flag for decision):** add the check 1
grep as a step in a lint/CI workflow (e.g. `code-quality.yml`) so a reintroduced `|| true` fails CI.
Directly serves the acceptance criterion "the same failure mode cannot silently reappear". Not
required by `design.md`; include only if approved.

## Design decisions requiring confirmation

These resolve the design's open questions and one review suggestion. Flagged because a reviewer may
prefer a different call; none is silently baked in beyond what the design already scopes.

1. **Open-question 1 — normalization breadth → full normalization.** All 22 `|| true` removals plus
   `--no-cache-dir` added, one canonical failure contract. (Design's own recommendation.)
2. **Open-question 2 — provenance assertion → deferred.** No third guard; Guards 1–2 close the bug.
   (Design's recommendation.)
3. **Open-question 3 — self-builders.** `build.sh`-based build logic is left intact for all six.
   However, the two self-builders that carry `|| true` (#22, #23) still get that token removed and
   #24 gains `set -e`, because these are install-block hygiene (not build logic) and are already
   within the design's "22 `|| true`" / "scripts lacking `set -e`" scope. Not converting any
   self-builder to the cache-based shape. (Consistent with the design; confirm the two `|| true`
   removals on immune scripts are wanted.)
4. **Open-question 4 — first-pass `--find-links` on Group B → rely on the un-swallowed
   `--no-index`.** No synthetic deps pass added to single-pass targets; this **withdraws review
   suggestion 3** on the evidence that those targets are `--no-deps`-only by construction. Confirm.

## Corrections to the research matrix

`research/issue_findings.md`'s per-script matrix has two errors, corrected by the mechanically
verified table above (a banner was added to that file):

1. `gcp-containerized/openai` **has** `|| true` on its `--no-index` line (`:13`); the matrix shows
   "–". It is in the set of 22.
2. `aws-serverless/scalable-openai` is **not** uniformly first-pass-`--find-links`: its request- and
   response-handler targets are single-pass `--no-deps --no-index` (Group-B-shaped); only the
   agent-runner target is two-pass. This widens Group B beyond `streaming`/`websocket`.

The headline counts in the findings (3 workflows / 6 restore steps; 22 `|| true`; 12 with `set -e`;
6 self-builders) are all confirmed accurate.
