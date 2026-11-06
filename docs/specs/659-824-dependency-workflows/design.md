# #659 and #824: Automated dependency updates and security fixes

One workflow covers both issues: `.github/workflows/dependency-update-copilot.yml` with
`.github/scripts/dependency_caps.py`. Every two weeks it limits, updates and secures every dependency, runs the
PR's CI, and opens one PR.

- **#659:** fix Dependabot alerts automatically, safely, in one PR.
- **#824:** keep every dependency up to date within safe limits.

## Motivation

- Most direct dependencies had no upper limit, so an update could jump a major. In PR #900, `openai` 2 → 3
  (pulled in by `openai-agents` 0.20 → 0.24) broke 11 test jobs with `Event loop is closed`.
- Thousands of Dependabot alerts were open across the repo's manifests (PR #901 fixed 3,800).
- An install check cannot see a broken update: unit tests mock the model and the examples need API keys. So the
  PR's own CI jobs must pass before the PR opens.

## Big picture

```mermaid
flowchart TD
    A[Every second Monday, or by hand] --> B[Cap, secure, update on each version line]
    B --> C{Installs?}
    C -- no --> D[Copilot names the package; hold it]
    C -- yes --> P
    D --> P[Check the patch: versions only, known registries; push]
    P --> E[Round 1: unit tests and e2e]
    E -- pass --> M[Open ONE PR]
    E -- fail --> F[Copilot names the package behind each real error; hold it]
    F --> G[Round 2: the same jobs]
    G -- pass, or only failures the update did not cause --> M
    G -- other failures --> J[Copilot labels each flaky, dependency or unsure, from the same job's history on other branches]
    J -- all flaky --> M
    J -- a dependency break, or unsure --> R[Open a DRAFT PR that lists them]
    G -- no results, or Copilot did not finish --> N[No PR; delete the branch; list the failures]
    M --> I[Start kind smoke and the weekly integration tests on the PR branch]
```

## Requirements

### Scope and schedule

- Every `pyproject.toml` with a `uv.lock` (131 manifests: ak-py, examples, use-cases, e2e, `agent/`), the same
  rules for each. No package lists in the code.
- Every second Monday, or by hand. Every run is a real run on every manifest (no inputs).
- One update PR at a time: an open PR with the `ak-dep-update` marker stops the run.
- If the alerts cannot be read, the run still caps and updates, and the PR says so at the top.

### Version rules

- A **version line** is the major for `1.x` and up, and the minor for `0.x`. No package leaves its line, direct or
  indirect, except to reach a security fix. Each held-back upgrade is listed ("needs its own PR").
- When uv moves a held package anyway (an upgraded package needs its new line), the package that pulls it is held
  too. Example: `openai-agents` 0.24 needs `openai` 3, so both stay.

| Package version | Upper limit added | Example |
|---|---|---|
| `1.x` and up | next major | `>=2.32.0,<3.0.0` |
| `0.x` | next minor | `>=0.27.0,<0.29.0` |
| date version | none | `certifi` stays open |

- Not capped, and listed in the PR: packages built in this repo (e.g. `agentkernel`), local sources, git/URL
  dependencies, date versions. A line that already has a limit keeps it.

| Security fix, declared as | Patched version | Becomes |
|---|---|---|
| `PyJWT>=2.13.0,<3.0.0` | 2.15.1 | `PyJWT>=2.15.1,<3.0.0` |
| `black==26.5.1` (a pin) | 26.10.1 | `black==26.10.1` |
| `litellm~=1.89.2` | 1.95.0 | `litellm>=1.95.0,<1.96` (keeps its width) |
| `daytona>=0.198.0,<0.199` | 0.200.0 | `daytona>=0.200.0,<0.201.0` (security wins) |

- npm: `npm audit fix` where npm alerts exist (never `--force`); no npm version updates.

### Checks and holds

- **Install check:** `uv lock` and `uv sync` for every manifest.
- **Test gate:** `test-reusable.yaml` (unit tests and e2e) on the pushed branch, two rounds at most. It already
  takes a `checkout_ref`, so no shared workflow changes.
- **On a failure** Copilot names the package that changed and brings the problem; the script holds it back.
- **A held security package:** kept at its security minimum when Copilot checked that the minimum works
  (`keep_minimum`), its declarations narrowed to that minor. Otherwise the fix is blocked, the original line comes
  back, and the alert stays open with the reason.
- A manifest that still fails is put back as it was. The other manifests still ship.

### Copilot

- Copilot only appends lines to `holds.jsonl`, `not_dependency.jsonl` and (after round 2) `judge.jsonl`; it never
  edits a file, commits or pushes.
- **Real error** (traceback, import error, resolver error, an error as the agent's answer): name
  the package. Example: `litellm` 1.108.0 imports `mcp.types.CacheableResult` → hold `litellm`, not `mcp`.
- **Same break elsewhere:** the gate does not test every manifest (the cloud examples deploy later). After a CI
  finding, Copilot checks other manifests that lock the same broken version and use the same part of the
  package, and holds it there too when it breaks the same way.
- **No dependency cause** (an answer only worded differently, an infra problem): no hold, a reason line instead.
- **Unsure:** nothing, so the failure goes on to round 2 unexplained.
- **After round 2 (`judge-2`), a separate prompt:** only round 2's failures with no pass in round 1 and no
  reason. The script first collects the same job's recent results in the normal Test workflow on other
  branches, with their error lines. Copilot labels each failure `flaky` (with evidence: the same failure on
  other branches, or a wording/infra failure with no error from a changed package), `dependency` (names the
  package) or `unsure`, in `judge.jsonl`. It holds nothing: there is no round 3 to test a hold.
- Tools: shell, read, write, PyPI URLs. The shell is not a sandbox, so Copilot only runs where no write token is.

### The PR

- Opens when a round passes, or when every failed job of the last round passed in round 1, has a Copilot
  "no dependency cause" reason, or is labelled `flaky` after round 2. Each is listed with its reason; the PR's
  own CI runs them again, and a real break fails there again.
- **A draft** when some failures are labelled `dependency` or `unsure`, or have no label. They are listed with
  Copilot's reason, for a person to decide.
- **No PR, branch deleted,** only when nothing can be judged: Copilot's fix job did not finish, or no results.
- Lists every change: version changes, security fixes by package, holds with reasons, blocked fixes, manifests put
  back, breaking upgrades held back, what is not covered, alerts still open, and accepted failures.
- After the PR opens, the workflows in `AFTER_PR_WORKFLOWS` start on its branch: `chart-test.yaml` (kind smoke) and
  `integration-test-weekly.yaml` with `provision_e2e_messaging=true` (the Slack/Telegram app is redeployed from the
  branch). Lint runs as a normal PR check. A reviewer reads them; nothing waits for them.
- Why kind and lint are not in the gate: calling them from this workflow needs a `checkout_ref` input, which CodeQL
  flags as cache poisoning (code from another branch runs with `develop`'s cache rights). Started on the branch
  itself, they need no change.

### Safety

- **Package code never runs next to a write token.** The update runs code from the packages it updates (build hooks,
  npm scripts, Copilot's own checks). That code runs as the same user as everything else in its job, so it can read
  any secret the job holds (for example from `/proc/<parent>/environ`) and replace files later steps run. So the
  jobs that run it (`update`, `fix-1`, `judge-2`) get a read-only token and the Copilot token only, and hand over a patch.
- **A patch is checked before it is pushed**, in a job that runs no package code:
  - only edits to tracked `pyproject.toml`, `uv.lock`, `package.json`, `package-lock.json` (no new, deleted,
    binary, renamed or mode-changed files, nothing under `.github/`);
  - `pyproject.toml` and `package.json` unchanged apart from version specifiers (same packages, extras, markers,
    no URLs, no new sections; an npm value stays a version range, not a git, file, URL or `npm:` source);
  - every `uv.lock` entry from PyPI (files from `files.pythonhosted.org`) or a relative path inside the repo;
    `package-lock.json` at lockfileVersion 2 or 3, every entry but the root from `registry.npmjs.org` with an
    `integrity` hash.
- **The script never comes from an artifact or a branch:** every job checks it out from the workflow's own commit.
  `packaging`, its one dependency, is pinned.
- **No `uv` cache** in this workflow, so package code cannot plant files that another run restores.
- No pre-releases. Never merges, never force-pushes. The `agent-kernel-ci[bot]` app pushes and opens the PR, so the
  PR's CI runs. Its token asks only for `contents: write` (push, delete the branch) and, in `finish`,
  `pull-requests: write`.

### Accepted risks

- **The Copilot token** sits in the jobs that run package code (Copilot itself runs `uv` to check minimums). A leak
  means use of the Copilot account, not repo access. Keep `COPILOT_REQUEST_TOKEN` a fine-grained token with only
  the Copilot permission.
- **The e2e keys** (`OPENAI_API_KEY` and the others) reach the code under test, as they do in the PR's own CI. Keep
  them scoped and with low limits.
- **A malicious release on PyPI or npm itself** passes the registry check; review and the PR's CI are the defence.
- **The PR body and Copilot's reasons** are written in jobs that run package code. They are only ever text or data
  (never run), so the worst case is a misleading description or a PR that opens with failing tests.

## Non-goals

- Code fixes (e.g. AK on `openai` 3): the package is held; the fix is a separate PR.
- Fixing flaky tests: they are listed in the PR, not fixed.
- Acting on the after-PR checks (kind smoke, integration tests, lint) automatically.
- Changes to the shared test workflows.

## Open questions

- Held-back majors: open one issue per held-back major so they are not forgotten?
