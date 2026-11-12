# #659 and #824: Dependency update workflow — specification

## Files

```text
.github/workflows/dependency-update-copilot.yml   # the workflow
.github/scripts/dependency_caps.py                # the script (all mechanical work, and the Copilot prompt)
agent/, examples/k8s/openai-queue-mode/, examples/sandbox/broker-nats/   # uv.lock now tracked
```

The shared workflows (`test-reusable.yaml`, `chart-test.yaml`, `code-quality.yml`) are unchanged.

## Triggers, permissions, secrets

- `schedule`: `0 3 * * 1` (Monday 03:00 UTC); the `prepare` job lets only even weeks since 1970 through
  (`date +%s / 604800 % 2 == 0`). Other triggers always run.
- `workflow_dispatch`: a real run by hand, no inputs (every run covers every manifest).
- Permissions (workflow default `contents: read`; each job sets its own):

| Job | Permissions | Secrets | Runs package code |
|---|---|---|---|
| `prepare` | `contents`, `pull-requests`, `security-events`: read | `DEPENDABOT_ALERTS_TOKEN` | no |
| `update`, `fix-1`, `judge-2` | `contents: read` (+ `actions: read` in `fix-1`, `judge-2`) | `COPILOT_REQUEST_TOKEN` | **yes** |
| `push`, `push-holds` | `contents: write` (+ `actions: write` in `push-holds`) | App key | no |
| `e2e-1`, `e2e-2` | `contents: read` | the e2e keys | **yes** (the tests) |
| `finish` | `contents`, `pull-requests`, `actions`: write | App key | no |

- Secrets: `COPILOT_REQUEST_TOKEN` (required); `APP_ID` + `APP_PRIVATE_KEY` (`agent-kernel-ci[bot]`: push and PR,
  so the PR's CI runs); `DEPENDABOT_ALERTS_TOKEN` (until the app can read alerts); the e2e secrets of
  `test-reusable.yaml` (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `WALLED_API_KEY`, `TYPESAFE_API_KEY`, `SLACK_BOT_TOKEN`,
  `SLACK_SIGNING_SECRET`).
- Settings in the workflow `env`: `BASE_BRANCH` (`develop`), `PR_TITLE`, `PACKAGING` (the pinned `packaging`),
  `SCRIPT` (the script in the `trusted` checkout of `github.sha`), `AFTER_PR_WORKFLOWS` (`chart-test.yaml integration-test-weekly.yaml:provision_e2e_messaging=true`; each entry is
  `<workflow file>[:<input>=<value>,...]`).

## Script commands

`uv run --no-project --with packaging==<PACKAGING> python dependency_caps.py [--root REPO] [--state DIR] <command>`

| Command | Does |
|---|---|
| `snapshot` | Saves the locked versions and the base commit; clears old state |
| `alerts` | Reads all open Dependabot alerts. On failure: a warning and `alerts-error.json`; the run continues |
| `cap` | Adds the next-line limit to each direct dependency without one; records the rest with a reason |
| `secure` | Raises each alerted direct dependency to its patched version |
| `update` | Per manifest: `LockGuard` (`uv lock --upgrade` on each version line), then `uv sync` |
| `failures` | Writes `failures.json` and prints the count. No `--jobs`: failing install checks. `--jobs` + `--run-id`: this run's failed CI jobs under those caller jobs, with logs |
| `fix` | Runs Copilot with the prompt, then `hold` |
| `evidence` | `--jobs e2e-1 --retry-jobs e2e-2`: writes `judge.json` with round 2's failed jobs that `verdict` cannot explain (no pass in round 1, no `not_dependency.jsonl` reason), each like a `failures.json` entry plus `history`: the same job (caller and matrix index ignored) in the last 30 completed `test.yaml` runs of this repository's own branches (no fork PRs: their logs are anyone's text, and their e2e jobs fail without secrets; no `deps/` branches): runs, passed, failed, and up to 3 failures with branch, date and error lines. Prints the count; a history call that fails is skipped |
| `judge` | Runs Copilot with the judge prompt on `judge.json` (nothing to judge: no Copilot). Copilot appends `{"job", "verdict": "flaky"\|"dependency"\|"unsure", "reason"}` to `judge.jsonl` |
| `hold` | Holds each package in `holds.jsonl` (`"*"` = every manifest where it moved); `keep_minimum` → pinned at the minimum (`pins.json`) and narrowed to its minor; otherwise a security package is `blocked`; checks those manifests again |
| `finalize` | Puts back every manifest that still fails |
| `npm` | `npm audit fix` where npm alerts exist; `npm ci` + `npm run build`; reverts on failure |
| `report` | Checks every alert again; writes `pr-body.md` and `update-summary.md` |
| `apply` | `--patch FILE`: checks a patch from a job that ran package code (rules below) and applies it; exit 1 and the reasons when it breaks a rule |
| `verdict` | `true` when every failed job of the last round passed in the other round or has a `not_dependency.jsonl` reason; `draft` when some have neither (flaky, or a break: listed as blocking); a round 2 failure labelled `flaky` in `judge.jsonl` counts as accepted (only for jobs in `judge.json`), any other label is shown next to the blocking job; `false` with no results. Lists every non-success, timeouts included, in the PR's Testing section (`verdict.json`). Lists the run's jobs with `gh api`, tried 3 times on HTTP 5xx; any other error stops the command |

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
- **Patch check (`apply`):** `git apply --summary` must print nothing (no new, deleted, renamed or mode-changed
  files); `--numstat` paths must be dependency files outside `.github/`, not binary, not symlinks. After applying:
  `pyproject.toml` parsed equals the version before apart from each requirement's specifier (name, extras, marker
  and URL must stay); `package.json` equals it apart from the versions in its dependency sections, and a changed value stays a
  version range (no `:` or `/`); `uv.lock` sources are `registry = "https://pypi.org/simple"` or a relative path
  inside the repo, files from `files.pythonhosted.org` or a plain file name in a local registry; `package-lock.json`
  is lockfileVersion 2 or 3 and every `packages` entry but the root has a `registry.npmjs.org` `resolved` and an
  `integrity`.
- **Alert check:** `uv.lock` alert → locked version ≥ patched; `pyproject.toml` alert → every floor ≥ patched;
  npm → `npm audit` reports 0. Every open alert gets a reason.

## Workflow jobs

| Job | Runs when | Does |
|---|---|---|
| `prepare` | always | `run=true` unless a scheduled run on an odd week or an update PR is open; `alerts` → artifact `alerts` |
| `update` | `prepare` says run | `$BASE_BRANCH`: `snapshot` → alerts copied in → `cap` → `secure` → `update` → up to 2 × (`failures` → `fix`) → `finalize` → `npm` → `report`; the dependency-file diff as `update.patch`; the state as artifact `update` |
| `push` | the patch is not empty | checks out the base commit (40 hex, on `$BASE_BRANCH`), `apply --patch update.patch`, commits, pushes `deps/update-batch-<RUN_ID>` |
| `e2e-1` | branch pushed | `test-reusable.yaml` (unit tests and e2e) with `checkout_ref` = the pushed commit |
| `fix-1` | `e2e-1` failed | `failures --jobs e2e-1` → `fix` → `finalize` → `report`; the diff as `holds.patch`; the state as artifact `holds` |
| `push-holds` | `fix-1` held something | `apply --patch holds.patch` on the pushed commit, commits, pushes; deletes this run's `ak-py-dist` artifact, which round 2 uploads again |
| `e2e-2` | not cancelled and `push-holds` succeeded | the same on the new commit (`!cancelled()`: GitHub's implied `success()` would see round 1's failure) |
| `judge-2` | `e2e-2` failed | deletes any inherited `judge.json`/`judge.jsonl`, then `evidence` (read-only `GITHUB_TOKEN` only) → `judge` (Copilot token only), on the round 2 commit; `judge.json` and `judge.jsonl` as artifact `judge`. `finish` deletes the copies in the other artifacts too, so labels count only from a successful `judge-2` |
| `finish` | branch pushed (also on cancel, then it only deletes the branch) | a round `success`, or `verdict` → `true`: `gh pr create --title $PR_TITLE`, then `gh workflow run <each of $AFTER_PR_WORKFLOWS> --ref <branch>` and one PR comment with their links (a failure to start is only a warning). `verdict` → `draft` (only when `fix-1` succeeded): the same, with `gh pr create --draft`. When `gh pr create` fails and no PR exists, delete the branch (a rerun keeps the run id, so the branch name) and fail. Else: delete the branch, list failed and blocking jobs, fail the run |

## Copilot prompt

One prompt in the script, for install-check and CI failures. Copilot reads `failures.json` and the logs as
untrusted data. For each failure:

1. Find the real error (traceback, import error, resolver or build error, an error as the answer).
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

- Title: `$PR_TITLE` (`chore(deps): update dependency versions and fix vulnerabilities`). Body follows the PR template;
  `Relates to #659, #824`.
- Hidden marker: `<!-- ak-dep-update manifests=<N> run=<RUN_ID> -->`. Author: the app (`<app-slug>[bot]`).

## How it is tested

Real runs on GitHub, started by a temporary `push` trigger on the feature branch (removed before merge): each push
ran the whole workflow (update, both rounds, PR). Results and the fixes they led to are in [plan.md](plan.md).
The patch check was run on the real update of run 42020023574 (270 files, accepted) and on 15 crafted patches (git
source, new dependency, `[build-system]`, URL requirement, new extra, changed marker, lock source or file host
changed, `postinstall` added, npm host changed, edits outside dependency files, new file, deleted file, symlink:
all rejected). `ruff`, `black -l 120` and `actionlint` pass.
