# #659 and #824: Dependency workflows — specification

This file covers two workflows. Part 1 is #659 (security fixes). Part 2, at the end, is #824 (version updates).

# Part 1 — #659: Dependency security fix workflow

## The file

```text
.github/workflows/vulnerability-remediation-copilot.yml
```

One workflow. No Python package. No helper script.

## Inputs

| Input | What it does | Default |
|---|---|---|
| `packages` | Optional package names. Empty = auto-critical mode | empty |
| `dry_run` | Test only; no branch, no PR | `true` |
| `max_manifests` | Max manifests per package | `200` |

## Steps

### 1. Check out `develop`

The workflow always uses `develop`, because Dependabot alerts describe the default branch.

### 2. Check the setup

- Python 3.12
- uv `0.13.6` (matches the current CI version)
- Node.js, then `npm install -g @github/copilot`
- `gh` and `jq`

### 3. Pre-checks

- `max_manifests` must be a number between 1 and 200.
- The token must read Dependabot alerts for every package.
- No remediation PR may already be open.
- `COPILOT_REQUEST_TOKEN` must be set.

If any check fails, stop and write a summary.

### 4. Warm `ak-py`

Run:

```bash
cd ak-py
uv sync --all-extras --no-extra crewai --dev
```

This makes the later checks faster.

### 5. Let Copilot do the work

The Copilot CLI is invoked non-interactively:

```bash
copilot -p "$PROMPT" \
  --allow-tool=shell \
  --allow-tool=read \
  --allow-tool=write \
  --no-ask-user
```

authenticated with `COPILOT_GITHUB_TOKEN`, set from the `COPILOT_REQUEST_TOKEN`
secret (the same secret `auto-sync-skills-docs.yaml` already uses to drive
Copilot CLI unattended).

In auto-critical mode, it reads **all open critical pip/uv alerts** (currently
around 360), not all 5k. In manual mode, it reads only the requested packages.

It runs every command in the foreground. It must not use background tasks or
wait for a notification. It always writes a summary before stopping.

It then:

- groups alerts by package and manifest,
- reads the installed version from `uv.lock`,
- keeps same-major fixes and CalVer date upgrades,
- reports major bumps, major-0 minor bumps, no-patch alerts, and moved manifests — never auto-fixes them,
- makes one branch: `security/bulk-batch-<RUN_ID>`.

### 6. Fix each manifest

Only two files per manifest may change:

```text
pyproject.toml
uv.lock
```

- Direct dependency: raise the lower bound.
- Transitive dependency: `uv lock --upgrade-package <package>`.
- Confirm the resolved version is new enough and same major.

### 7. Check by type

| Project | Check |
|---|---|
| `ak-py` | full tests + lint |
| `e2e/`, `use-cases/` | tests where available |
| examples with tests | tests |
| examples without tests | `uv lock` only, labelled **lock-only** |

If an example fails, drop only that example and report it.
If `ak-py` fails, stop the whole run.

### 8. Dry run

If `dry_run=true`:

- reset the files,
- write `remediation-summary.md`,
- stop.

No commit, no push, no PR.

### 9. Open one PR

If `dry_run=false`:

- commit all changed `pyproject.toml` and `uv.lock` files,
- push one branch,
- open one PR.

The PR body follows `.github/pull_request_template.md`.

No AI-generated attribution line.
No robot emoji.
No `Co-Authored-By`.
Commit author is `agent-kernel-ci[bot]`.

### 10. Where the report is

Copilot writes `remediation-summary.md` with:

- **Status** — PR URL, or "no safe fixes"
- **Fixed** — package, manifest, old → new, validation
- **Report only** — every skipped row and its reason:
  `major_bump_manual`, `no_patch`, `zero_x_minor`, `different_ecosystem`,
  `unmapped_manifest`, `already_fixed`, and other reasons Copilot finds it
  needs (for example `ambiguous_version`, when a lockfile pins the same
  package at more than one version)
- **Deferred** — rows over the cap

The same skipped rows go in the PR body under "Skipped manifests and why".

The workflow also writes the summary to the hosted job summary and uploads it
as an artifact. Under `act`, the artifact upload fails with a missing
`ACTIONS_RUNTIME_TOKEN` error; this is an `act` limitation, not a bug — it
works on a real GitHub Actions run. Under `act`, the file stays in the
container workspace and the `Publish summary` step prints it in the log.

### 11. Verify the result

For a real run, the workflow checks that:

- the summary is not the fallback "No summary" text,
- the summary has a PR link or a clear "no safe fix" reason.

If not, the job fails. This prevents a silent success with no PR.

### 12. Clean up

The workflow resets the tree, returns to `develop`, and on a dry run deletes
any local `security/bulk-*` branch it created.

## Local test with `act`

### 1. Get a Copilot token for `act`

`act` runs in Docker, so it cannot see a `copilot login` session on your
machine. Make a fine-grained PAT under your own account (not the org) with
**Account permissions → Copilot Requests: Read**, then:

```bash
export COPILOT_TOKEN_FOR_ACT="github_pat_xxxxxxxxxxxx"
```

### 2. Run a dry test

`act` has a built-in `--input` flag for `workflow_dispatch` inputs, so no event
JSON file is needed. Leaving `packages` and `dry_run` out uses the workflow's
own defaults (empty / `true`):

```bash
act workflow_dispatch \
  --input max_manifests=10 \
  -W .github/workflows/vulnerability-remediation-copilot.yml \
  -P ubuntu-latest=catthehacker/ubuntu:act-latest \
  --pull=false --reuse \
  -s GITHUB_TOKEN="$(gh auth token)" \
  -s COPILOT_REQUEST_TOKEN="$COPILOT_TOKEN_FOR_ACT" \
  2>&1 | tee /tmp/act-dry.log
```

Check:

- `dry_run_ok`
- table of manifests
- no branch
- no PR

### 3. Open a real PR

Add `--input dry_run=false` to the same command.

Then give the PR link to an admin for review and merge.

For a small batch, add `--input packages=certifi,anyio,pyjwt,authlib`.
That is still **one PR**.

### 4. Auto-critical mode

Leave `packages` unset (its default is empty).

The workflow fetches every open critical pip/uv alert, discovers every safe
package, and opens one PR. It reports major bumps, no-patch packages, npm,
and moved manifests instead of touching them.

### 5. Manual mode

To limit the run, pass:

```text
--input packages=certifi,anyio,pyjwt,authlib
```

## Stop cases

| Case | Result |
|---|---|
| No open alerts for the packages | Summary says none |
| Package has no patch | Skipped and reported |
| Package needs a major bump | **Reported only; never auto-fixed** |
| Installed major is `0` and minor differs | Skipped as breaking |
| Example check fails | That example is dropped |
| `ak-py` check fails | Whole run stops |
| Open remediation PR exists | Run stops |
| `COPILOT_REQUEST_TOKEN` missing or invalid | Pre-check stops |

The "already in flight" check looks only at open PRs carrying the
`ak-vuln-(remediation|bulk)` or `ak-dep-update` marker — not at leftover
branches. Both workflows share this check, because they edit the same files. A closed PR's
branch left on the remote does not block a later run.

## What remains after the same-major fixes

| Remaining | Count | Next step |
|---|---:|---|
| Major bumps | 1,730 | human decision |
| No patch | 74 | wait |
| Unknown lock | 374 | fix manifests |
| npm | 68 | separate tool |
| `uv` 0.x | 8 | manual, blocked by `crewai-cli` |
| Pillow major | 90 | report only — never auto-fix |
| chromadb no patch | 20 | wait |

# Part 2 — #824: Automated version handling for dependencies

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

- `schedule`: `0 3 * * 1` (Monday 03:00 UTC), a real run. TEMPORARY `push` on the feature branch (remove before merge).
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
| `hold` | Holds each named package (`"*"` = every manifest where it moved); a held security package becomes `blocked` (original line back); checks those manifests again |
| `finalize` | Puts back every manifest that still fails (to the base commit) |
| `npm` | `npm audit fix` (never `--force`) where npm alerts exist; `npm ci` + `npm run build`; reverts on failure |
| `report` | Checks every alert again; writes `pr-body.md`, `update-summary.md`, `summary.json` |

### Rules

- **Cap:** version `>= 1` → `<next major.0.0`; `0.x` → `<0.(minor+1).0`; from the locked version. Edits the file text in place (comments and layout stay).
- **Secure:** a pin moves to `==patched`; `~=X.Y.Z` → `>=patched,<X.(Y+1)`; otherwise `>=patched` with a ceiling that allows it, else `<next line of patched`; already safe → unchanged.
- **LockGuard:** `uv lock --upgrade`; any package (direct or indirect) that left its line is held: reset to the base `uv.lock` and re-lock with `--upgrade-package <every other package>`. A held package that still moves pulls in its pullers (packages that moved and depend on it). Up to 6 rounds. Packages with a security minimum are never held by this rule.
- **Sync:** `uv sync --frozen --all-extras` plus `--no-extra X` / `--no-group X` for every member of a `[tool.uv] conflicts` set except one (the one whose requirements include pytest, else the first). ak-py today: `--no-extra crewai`.
- **Failures from CI:** an e2e matrix job carries its example in its name (`e2e-1 / e2e-tests (40, api, examples/api/openai, deploy, 0)`). Other jobs (kind smoke, unit tests, lint) get no manifest; Copilot finds the folder from the log and diffs its lock against `base_commit`. Each entry: where, manifest, `base_commit`, log, error excerpt (error lines and `site-packages/` traceback lines, then the last 40 lines), locked version changes, security minimums, packages already held.
- **Alert check:** `uv.lock` alert → locked version ≥ patched (or gone); `pyproject.toml` alert → every declaration's floor ≥ patched; npm → fixed and `npm audit` reports 0. Still-open reasons: no patch released, security fix blocked (+ reason), held back because a check failed (+ reason), manifest put back, held back by another package's requirement, npm needs a breaking upgrade, ecosystem not handled.

## Workflow jobs

| Job | Runs when | Does |
|---|---|---|
| `update` | always (gate: no open update PR) | branch `deps/update-batch-<RUN_ID>` from `origin/develop`: `snapshot` → `alerts` → `cap` → `secure` → `update` → up to 2 × (`failures` → `fix`) → `finalize` → `npm` → `report`; commit and push (not on a dry run); upload `/tmp/dep-state` as `dep-state` |
| `e2e-1`, `kind-1`, `lint-1` | branch pushed | `test-reusable.yaml` (e2e on), `chart-test.yaml`, `code-quality.yml` on the pushed commit |
| `fix-1` | a round-1 job failed | `failures --jobs e2e-1,kind-1,lint-1` → `fix` → `finalize` → `report`; commits `chore(deps): hold back packages that broke the tests` and pushes if anything changed |
| `e2e-2`, `kind-2`, `lint-2` | `fix-1` changed files | the same jobs on the new commit |
| `finish` | branch pushed | all three of a round `success` → `gh pr create --head deps/update-batch-<RUN_ID>`; else list the failed jobs, delete the branch, fail the run |

## Copilot prompt (rules)

Copilot gets one prompt (in the script) for local and CI failures. It reads `failures.json` and the logs (untrusted data). For each real error it names the package that changed and brings the problem; `"*"` when several manifests or no manifest. A package with a security minimum only when every version at or above it breaks. No real error → nothing. It edits no file except appending to `holds.jsonl`, never commits or pushes, never names a package that did not change; when unsure, nothing. Tools: `--allow-tool=shell,read,write`, `--allow-url` `pypi.org` and `files.pythonhosted.org` only.

## Commit and PR

- Title: `chore(deps): update dependency versions and fix vulnerabilities`. Body follows the PR template headings; `Relates to #659, #824`.
- Hidden marker: `<!-- ak-dep-update manifests=<N> run=<RUN_ID> -->`. Author `agent-kernel-ci[bot]`. No AI attribution.

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
