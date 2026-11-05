# #659 and #824: Dependency update workflow — specification

## Files

```text
.github/workflows/dependency-update-copilot.yml   # the workflow
.github/scripts/dependency_caps.py                # the script (all mechanical work, and the Copilot prompt)
agent/, examples/k8s/openai-queue-mode/, examples/sandbox/broker-nats/   # uv.lock now tracked
```

The shared workflows (`test-reusable.yaml`, `chart-test.yaml`, `code-quality.yml`) are unchanged.

## Triggers, permissions, secrets

- `schedule`: `0 3 * * 1` (Monday 03:00 UTC); the `when` job lets only even weeks since 1970 through
  (`date +%s / 604800 % 2 == 0`). Other triggers always run.
- TEMPORARY `push` on the feature branch, for real test runs. Removed before merge.
- `workflow_dispatch`: a real run by hand, no inputs (every run covers every manifest).
- Permissions: `contents: write`, `pull-requests: write`, `security-events: read`, `actions: read`; `fix-1` and
  `finish` also `actions: write` (delete an artifact; start workflows).
- Secrets: `COPILOT_REQUEST_TOKEN` (required); `APP_ID` + `APP_PRIVATE_KEY` (`agent-kernel-ci[bot]`: push and PR,
  so the PR's CI runs); `DEPENDABOT_ALERTS_TOKEN` (until the app can read alerts); the e2e secrets of
  `test-reusable.yaml` (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `WALLED_API_KEY`, `TYPESAFE_API_KEY`, `SLACK_BOT_TOKEN`,
  `SLACK_SIGNING_SECRET`).
- Settings in the workflow `env`: `BASE_BRANCH` (`develop`), `AFTER_PR_WORKFLOWS` (`chart-test.yaml integration-test-weekly.yaml`).

## Script commands

`uv run --no-project --with packaging python .github/scripts/dependency_caps.py [--state DIR] <command>`

| Command | Does |
|---|---|
| `snapshot` | Saves the locked versions and the base commit; clears old state |
| `alerts` | Reads all open Dependabot alerts. On failure: a warning and `alerts-error.json`; the run continues |
| `cap` | Adds the next-line limit to each direct dependency without one; records the rest with a reason |
| `secure` | Raises each alerted direct dependency to its patched version |
| `update` | Per manifest: `LockGuard` (`uv lock --upgrade` on each version line), then `uv sync` |
| `failures` | Writes `failures.json` and prints the count. No `--jobs`: failing install checks. `--jobs` + `--run-id`: this run's failed CI jobs under those caller jobs, with logs |
| `fix` | Runs Copilot with the prompt, then `hold` |
| `hold` | Holds each package in `holds.jsonl` (`"*"` = every manifest where it moved); `keep_minimum` → pinned at the minimum (`pins.json`) and narrowed to its minor; otherwise a security package is `blocked`; checks those manifests again |
| `finalize` | Puts back every manifest that still fails |
| `npm` | `npm audit fix` where npm alerts exist; `npm ci` + `npm run build`; reverts on failure |
| `report` | Checks every alert again; writes `pr-body.md`, `update-summary.md`, `summary.json` |
| `verdict` | `true` when every failed job of the last round passed in round 1 or has a `not_dependency.jsonl` reason; then lists them in the PR's Testing section (`verdict.json`) |

### Rules

- **Cap:** `>= 1` → `<next major.0.0`; `0.x` → `<0.(minor+1).0`; from the locked version. Edits the text in place.
- **Secure:** a pin → `==patched`; `~=X.Y.Z` → `>=patched,<X.(Y+1)` while patched fits, else the same width at
  patched (`~=1.89.2` + 1.95.0 → `>=1.95.0,<1.96`); otherwise `>=patched` under a ceiling that allows it; already
  safe → unchanged.
- **LockGuard:** after `uv lock --upgrade`, a package that left its line is held: re-lock from the base lock with
  `--upgrade-package` for every other package. A held package that still moves pulls in the packages that need it.
  Up to 6 rounds. Security packages are not held by this rule; a pinned one is re-locked at its pin.
- **Sync:** `uv sync --frozen --all-extras`, leaving out all but one member of each `[tool.uv] conflicts` set (the
  one that brings pytest).
- **CI failures:** a job whose name holds a manifest folder (`e2e-1 / e2e-tests (40, api, examples/api/openai,
  deploy, 0)`) gets that manifest, the longest match. Other jobs get none; Copilot finds the folder from the log.
  Each entry: where, manifest, base commit, log, error excerpt, locked version changes, security minimums, held
  packages.
- **Alert check:** `uv.lock` alert → locked version ≥ patched; `pyproject.toml` alert → every floor ≥ patched;
  npm → `npm audit` reports 0. Every open alert gets a reason.

## Workflow jobs

| Job | Runs when | Does |
|---|---|---|
| `when` | always | `run=true` unless a scheduled run on an odd week |
| `update` | `when` says run, no open update PR | branch `deps/update-batch-<RUN_ID>` from `$BASE_BRANCH`: `snapshot` → `alerts` → `cap` → `secure` → `update` → up to 2 × (`failures` → `fix`) → `finalize` → `npm` → `report`; commit, push, upload the state as `dep-state` |
| `e2e-1` | branch pushed | `test-reusable.yaml` (unit tests and e2e) with `checkout_ref` = the pushed commit |
| `fix-1` | `e2e-1` failed | `failures --jobs e2e-1` → `fix` → `finalize` → `report`; commits and pushes the holds; deletes this run's `ak-py-dist` artifact, which round 2 uploads again |
| `e2e-2` | `always()` and `fix-1` changed files | the same on the new commit (`always()`: GitHub's implied `success()` would see round 1's failure) |
| `finish` | branch pushed | a round `success`, or `verdict` → `true`: `gh pr create`, then `gh workflow run <each of $AFTER_PR_WORKFLOWS> --ref <branch>` and one PR comment with their links (a failure to start is only a warning). Else: delete the branch, list failed and blocking jobs, fail the run |

## Copilot prompt

One prompt in the script, for install-check and CI failures. Copilot reads `failures.json` and the logs as
untrusted data. For each failure:

1. Find the real error (traceback, import error, resolver or build error, lint failure, an error as the answer).
2. Name the package that changed and brings the problem (the prompt's example is made up, so it cannot be copied).
3. Append `{"manifest", "package", "reason"}` to `holds.jsonl` (`"*"` for several manifests or none). CI failures
   only: find other `uv.lock` files with the same broken version; where the manifest uses the same part of the
   package, repeat the failing import there and add a line ("same break as <manifest>") when it breaks.
4. A security package: repeat the failing import with the minimum in `/tmp`. Works → `"keep_minimum": true`;
   breaks → no flag; not checked → reason starts "not verified:".
5. No dependency cause: `{"job", "reason"}` in `not_dependency.jsonl`, only when sure.

Hard rules: append to those two files only; never commit or push; never name a package that did not change; when
unsure, nothing. Tools: `shell`, `read`, `write`; URLs `pypi.org` and `files.pythonhosted.org` only.

## Commit and PR

- Title: `chore(deps): update dependency versions and fix vulnerabilities`. Body follows the PR template;
  `Relates to #659, #824`.
- Hidden marker: `<!-- ak-dep-update manifests=<N> run=<RUN_ID> -->`. Author: the app (`<app-slug>[bot]`).

## How it is tested

Real runs on GitHub, started by the temporary `push` trigger: each push runs the whole workflow (update, both
rounds, PR). Results and the fixes they led to are in [plan.md](plan.md). `ruff`, `black -l 120` and `actionlint`
pass.
