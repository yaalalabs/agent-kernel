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
.github/workflows/dependency-update-copilot.yml
.github/scripts/dependency_caps.py
```

## Triggers and inputs

- `schedule`: `0 3 * * 1` (Monday 03:00 UTC). Full run, `dry_run=false`.
- `workflow_dispatch` inputs:

| Input | What it does | Default |
|---|---|---|
| `paths` | Path prefixes, comma-separated, for test runs. Empty = everything | empty |
| `dry_run` | Test only; no branch, no PR | `true` |

Permissions: `contents: write`, `pull-requests: write`, `security-events: read`.
Secrets: `COPILOT_REQUEST_TOKEN` (required); `DEPENDABOT_ALERTS_TOKEN` (optional, falls back to `GITHUB_TOKEN`).

## Script commands

Run with `uv run --no-project --with packaging python .github/scripts/dependency_caps.py <command> [--paths ...] [--state ...]`.

| Command | What it does |
|---|---|
| `snapshot` | Saves locked versions and the base commit; clears old state |
| `alerts` | Reads all open Dependabot alerts with `gh api` (fails the run if it cannot) |
| `restrict` | Adds an upper limit to each unrestricted direct dependency |
| `lift` | Raises a single `<` limit where PyPI has a newer stable release (skips lines with a comment above) |
| `secure` | Makes each alerted direct dependency require its patched version (wins over comments) |
| `validate` | `uv lock --upgrade` and the checks, per manifest (non-ak-py: 4 in parallel) |
| `failures` | Prints how many manifests fail |
| `security-fallback` | For each failing manifest with alerts: reset it, apply `secure` only, `uv lock --upgrade-package <alerted>`, check again |
| `finalize` | Reverts manifests that still fail; exit code 3 if `ak-py` is one |
| `unlocked` | `secure` for manifests without `uv.lock`, verified with `uv pip compile` |
| `npm` | `npm audit fix` (never `--force`) where npm alerts exist; `npm ci` + `npm run build`; reverts on failure |
| `report` | Checks every alert again; writes `pr-body.md`, `update-summary.md`, `still-open.json` |

### Limit rules

- Version `>= 1`: `<next major.0.0`. Version `0.x`: `<0.(minor+1).0`. Built from the locked version.
- Date versions (first part `>= 2000`): no limit.
- Skipped: `agentkernel`, the project's own name, names in `[tool.uv.sources]`, strings with `<`, `<=`, `~=`, `==`, `===`.
- File text is edited in place; comments and layout stay.

### Security rules (`secure`)

- `==X` below the fix → `==patched` (a pin stays a pin).
- `~=X.Y.Z` → `>=patched,<X.(Y+1)` when the ceiling still allows the fix; otherwise `<next major of patched`.
- Otherwise: floor becomes `>=patched`; a ceiling that allows the fix is kept, else `<next major of patched`.
- Already safe (floor at or above the fix) → unchanged.

### Checks (`validate --level full`)

| Manifest | Steps |
|---|---|
| `ak-py` | `uv lock --upgrade`, `uv sync --all-extras --no-extra crewai --dev`, `uv run pytest`, `make lint-check` |
| others | `uv lock --upgrade`, `uv sync --frozen`, `uv run pytest` if it has tests |

A non-ak-py `pytest` failure is checked against the base commit (a `git worktree` of the snapshot commit). If the tests fail there too, the manifest passes with note `tests_failing_before`.

Each command has a 30-minute timeout.

### Alert check (`report`)

| Alert on | Fixed when |
|---|---|
| `uv.lock` | locked version is at or above the patched version (or the package is gone) |
| `pyproject.toml` | every declaration of the package has a floor at or above the patched version |
| npm `package-lock.json` | npm step fixed it and `npm audit` reports 0 left |

Still-open reasons: `no patch released`, `held back by another package's limit`, `manifest failed its checks and was reverted`, `declared range still allows the vulnerable version`, `npm: needs a breaking upgrade`, `npm: fix broke the build and was reverted`.

## Workflow steps

1. Check out `develop`; set up Python 3.12, uv `0.13.6`, Node, Copilot CLI, `gh`, `jq`.
2. **Gate:** stop if an open PR has the `ak-vuln-(remediation|bulk)` or `ak-dep-update` marker.
3. Check `COPILOT_REQUEST_TOKEN`. Warm `ak-py`.
4. **Main step**, on branch `deps/update-batch-<RUN_ID>`:
   `snapshot` → `alerts` → `restrict` → `lift` → `secure` → `validate --upgrade` →
   fix loop (up to 3 × Copilot + `validate --only-failed`) → `security-fallback` → `finalize` →
   `unlocked` → `npm` → `report`.
   If `finalize` exits 3 (`ak-py` failed), restore the tree, fail the job, no PR.
5. **Open PR** if `dry_run=false` and files changed: add changed `pyproject.toml`, `uv.lock`, `package.json`, `package-lock.json`; commit; push; `gh pr create`.
6. Publish summary, verify, upload artifact, clean up.

## Copilot fix prompt (rules)

- Read `/tmp/dep-state/failures.json` (error tail, limit changes, security minimums, version changes).
- Restore the package that broke; run `uv lock` (no `--upgrade`).
- Only the failing manifest's `pyproject.toml` and `uv.lock`.
- Never below a security minimum. Never commit, push, or run the full tests.

## Commit and PR

- Title: `chore(deps): update dependency versions and fix vulnerabilities`
- Body follows `.github/pull_request_template.md`; `Relates to #659, #824`.
- Hidden marker: `<!-- ak-dep-update manifests=<N> run=<RUN_ID> -->`
- No AI attribution, no robot emoji, no `Co-Authored-By`. Author `agent-kernel-ci[bot]`.

## Local checks done

On a throwaway clone of `develop`, with the live alerts (5,544 read in about 80 seconds):

- 3 manifests (`examples/api/agui`, `examples/k8s/openai-queue-mode`, `examples/sandbox/broker-nats`): limits added, a limit raised, `black==26.5.1` → `black==26.10.1` in all three (two have no `uv.lock`), npm fixed in `examples/api/agui/frontend`.
- `examples/api/agui` tests failed on the base commit too → counted as `tests_failing_before`, not a failure.
- **37 alerts fixed, 20 still open**, each with a reason (`filelock` held back by `litellm`/`huggingface-hub`; `vite` needs a breaking npm upgrade; `PyJWT` has no patch).
- **Fallback test:** a manifest broken on purpose fell back to security fixes only, passed, and still fixed 35 alerts.
- `secure` rules checked on 13 hand-written cases (pins, `~=`, markers, extras, documented limits).
- `ruff check` passes.

Not tested yet: the Copilot fix loop, the full run time, the PR step, and `GITHUB_TOKEN` reading alerts on GitHub.

## Local test with `act`

```bash
act workflow_dispatch \
  --input paths=examples/api/agui \
  --input dry_run=true \
  -W .github/workflows/dependency-update-copilot.yml \
  -P ubuntu-latest=catthehacker/ubuntu:act-latest \
  --pull=false --reuse \
  -s GITHUB_TOKEN="$(gh auth token)" \
  -s COPILOT_REQUEST_TOKEN="$COPILOT_TOKEN_FOR_ACT" \
  2>&1 | tee /tmp/act-dep-dry.log
```
