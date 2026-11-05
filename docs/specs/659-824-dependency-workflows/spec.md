# #659 and #824: Dependency update workflow — specification


## The files

```text
.github/workflows/dependency-update-copilot.yml   # the workflow
.github/scripts/dependency_caps.py                # the script
.github/workflows/test-reusable.yaml              # upload `overwrite: true` (called twice in one run)
.github/workflows/chart-test.yaml                 # `workflow_call` with `checkout_ref` + OPENAI_API_KEY
.github/workflows/code-quality.yml                # `workflow_call` with `checkout_ref`
agent/, examples/k8s/openai-queue-mode/, examples/sandbox/broker-nats/   # uv.lock now tracked
```

## Triggers, inputs, permissions, secrets

- `schedule`: `0 3 * * 1` (Monday 03:00 UTC), a real run; the `when` job lets only even weeks since 1970 through (`date +%s / 604800 % 2 == 0`), so every second Monday. Manual and push runs always go ahead. TEMPORARY `push` on the feature branch (remove before merge).
- `workflow_dispatch`: `paths` (prefixes; empty = everything), `dry_run` (default `true`: update and check locally only).
- Permissions: `contents: write`, `pull-requests: write`, `security-events: read`, `actions: read` (failed jobs' logs).
- Secrets: `COPILOT_REQUEST_TOKEN` (required); `APP_ID` + `APP_PRIVATE_KEY` (`agent-kernel-ci[bot]`: push and PR, so the PR's CI runs); `DEPENDABOT_ALERTS_TOKEN` (alerts, until the app can read them); the e2e secrets passed to `test-reusable.yaml` (`OPENAI_API_KEY`, `WALLED_API_KEY`, `TYPESAFE_API_KEY`, `SLACK_BOT_TOKEN`, `SLACK_SIGNING_SECRET`).

## Script commands

Run with `uv run --no-project --with packaging python .github/scripts/dependency_caps.py <command> [--paths ...] [--state /tmp/dep-state]`.

| Command | What it does |
|---|---|
| `snapshot` | Saves the locked versions and the base commit; clears the previous run's state |
| `alerts` | Reads all open Dependabot alerts with `gh api`. On failure: a warning, `alerts-error.json`, and the run continues |
| `cap` | Adds `<next line>` to each direct dependency without an upper limit; records `not_limited` + reason for the rest |
| `secure` | Raises each alerted direct dependency to its patched version (rules below) |
| `update` | Per manifest (4 in parallel): `LockGuard` (`uv lock --upgrade` on each version line), then `uv sync` |
| `failures` | Writes `failures.json` for Copilot and prints the count. No `--jobs`: failing local checks. `--jobs e2e-1,kind-1,lint-1 --run-id <id>`: this run's failed CI jobs under those caller jobs, with their logs |
| `fix` | Runs Copilot with the prompt (it appends to `holds.jsonl`), then `hold` |
| `hold` | Holds each named package (`"*"` = every manifest where it moved); a held security package with `keep_minimum` (and a newer version locked) is kept at its minimum (`pins.json`; declarations narrowed to the minimum's minor); otherwise it becomes `blocked` (original line back, any pin dropped); checks those manifests again |
| `finalize` | Puts back every manifest that still fails (to the base commit) |
| `npm` | `npm audit fix` (never `--force`) where npm alerts exist; `npm ci` + `npm run build`; reverts on failure |
| `report` | Checks every alert again; writes `pr-body.md`, `update-summary.md`, `summary.json` |

### Rules

- **Cap:** version `>= 1` → `<next major.0.0`; `0.x` → `<0.(minor+1).0`; from the locked version. Edits the file text in place (comments and layout stay).
- **Secure:** a pin moves to `==patched`; `~=X.Y.Z` → `>=patched,<X.(Y+1)` while patched fits, else the same width at patched (`~=1.89.2` + 1.95.0 → `>=1.95.0,<1.96`); otherwise `>=patched` with a ceiling that allows it, else `<next line of patched`; already safe → unchanged.
- **LockGuard:** `uv lock --upgrade`; any package (direct or indirect) that left its line is held: reset to the base `uv.lock` and re-lock with `--upgrade-package <every other package>`. A held package that still moves pulls in its pullers (packages that moved and depend on it). Up to 6 rounds. Packages with a security minimum are never held by this rule. A pinned package is re-locked with `--upgrade-package <name>==<minimum>` and counts as "moved" only when it leaves its pin.
- **Sync:** `uv sync --frozen --all-extras` plus `--no-extra X` / `--no-group X` for every member of a `[tool.uv] conflicts` set except one (the one whose requirements include pytest, else the first). ak-py today: `--no-extra crewai`.
- **Failures from CI:** a job whose name mentions a manifest folder (an e2e matrix job: `e2e-1 / e2e-tests (40, api, examples/api/openai, deploy, 0)`) gets that manifest, the longest match, so `cli/adk` is not `cli/adk_context`; no job-name format is assumed. Other jobs (kind smoke, unit tests, lint) get no manifest; Copilot finds the folder from the log and diffs its lock against `base_commit`. Each entry: where, manifest, `base_commit`, log, error excerpt (error lines and `site-packages/` traceback lines, then the last 40 lines), locked version changes, security minimums, packages already held.
- **Alert check:** `uv.lock` alert → locked version ≥ patched (or gone); `pyproject.toml` alert → every declaration's floor ≥ patched; npm → fixed and `npm audit` reports 0. Still-open reasons: no patch released, security fix blocked (+ reason), held back because a check failed (+ reason), manifest put back, held back by another package's requirement, npm needs a breaking upgrade, ecosystem not handled.

## Workflow jobs

| Job | Runs when | Does |
|---|---|---|
| `when` | always | `run=true` unless a scheduled run on an odd week |
| `update` | `when` says run (gate: no open update PR) | branch `deps/update-batch-<RUN_ID>` from `origin/$BASE_BRANCH` (`develop`, set once in the workflow `env`): `snapshot` → `alerts` → `cap` → `secure` → `update` → up to 2 × (`failures` → `fix`) → `finalize` → `npm` → `report`; commit and push (not on a dry run); upload `/tmp/dep-state` as `dep-state` |
| `e2e-1`, `kind-1`, `lint-1` | branch pushed | `test-reusable.yaml` (e2e on), `chart-test.yaml`, `code-quality.yml` on the pushed commit |
| `fix-1` | a round-1 job failed | `failures --jobs e2e-1,kind-1,lint-1` → `fix` → `finalize` → `report`; commits `chore(deps): hold back packages that broke the tests` and pushes if anything changed |
| `e2e-2`, `kind-2`, `lint-2` | `always() &&` `fix-1` changed files (without `always()` GitHub's implied `success()` sees round 1's failure and skips them) | the same jobs on the new commit |
| `finish` | branch pushed | all three of a round `success` → `gh pr create --head deps/update-batch-<RUN_ID>`; else list the failed jobs, delete the branch, fail the run |

## Copilot prompt (rules)

Copilot gets one prompt (in the script) for local and CI failures. It reads `failures.json` and the logs (untrusted data). For each real error it names the package that changed and brings the problem; `"*"` when several manifests or no manifest. A package with a security minimum: Copilot repeats the failing import with the minimum (`uv run --no-project --with <pkg>==<minimum>` in `/tmp`); works → `"keep_minimum": true`; breaks → no flag, said in the reason; not checked → no flag, reason starts "not verified:". The prompt's example is made up, so it cannot be copied as a finding. No real error → nothing. It edits no file except appending to `holds.jsonl`, never commits or pushes, never names a package that did not change; when unsure, nothing. Tools: `--allow-tool=shell,read,write`, `--allow-url` `pypi.org` and `files.pythonhosted.org` only.

## Commit and PR

- Title: `chore(deps): update dependency versions and fix vulnerabilities`. Body follows the PR template headings; `Relates to #659, #824`.
- Hidden marker: `<!-- ak-dep-update manifests=<N> run=<RUN_ID> -->`. Author: the pushing app (`<app-slug>[bot]`). No AI attribution.

## Local checks done

On a worktree of `develop`, with the live alerts:

- Rules: 9 `secure` cases (pins, `~=`, markers, extras, documented limits, already safe), version lines and caps.
- `examples/api/openai` + `examples/cli/adk*` (5 manifests): 5,543 alerts read; 10 caps; 5 security raises; `update` in 24 seconds with `openai` held at 2.54 and `openai-agents` at 0.20; 186 alerts fixed.
- `hold` with `{"manifest": "*", "package": "litellm"}`: back to develop's version in the 4 manifests where it moved; a malformed line ignored; `litellm`'s own alerts reported as "security fix blocked" with the reason; one manifest where `litellm` did not move reported as "held back by another package's requirement".
- `failures --jobs run-tests` on PR #900's real test run: all 16 failed jobs found, mapped to their examples, logs saved.
- Full repo `cap` on develop: 409 limits; 257 dependencies left without one, all reported (all `agentkernel`). `alerts` against a missing repo: warning, exit 0, PR warning.
- `ruff check`, `ruff format --check`, `actionlint` (the workflow and the three called workflows) pass.

Not tested yet: the workflow on GitHub end to end (jobs chaining, Copilot on real CI logs, the PR).

## Local test with `act`

`act` can run the `update` job only (a dry run); the test gate needs GitHub.

```bash
act workflow_dispatch \
  --input paths=examples/api/agui \
  --input dry_run=true \
  -W .github/workflows/dependency-update-copilot.yml -j update \
  -P ubuntu-latest=catthehacker/ubuntu:act-latest \
  --pull=false \
  -s GITHUB_TOKEN="$(gh auth token)" \
  -s COPILOT_REQUEST_TOKEN="$COPILOT_TOKEN_FOR_ACT" \
  2>&1 | tee /tmp/act-dep-dry.log
```
