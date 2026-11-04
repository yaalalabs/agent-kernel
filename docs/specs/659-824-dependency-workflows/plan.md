# #659: Dependency security fix workflow — plan

## Status

- Workflow written: `.github/workflows/vulnerability-remediation-copilot.yml`, driven by the GitHub Copilot CLI (not Claude).
- Schema and shell checks pass.
- Auto-critical mode added: leave `packages` empty and the workflow discovers every safe critical package.
- Major semver bumps are **never auto-fixed**; they are report-only.
- CalVer date upgrades (for example certifi) are allowed.
- Dry-run auto-critical mode: done, both via direct `copilot -p` and the full workflow under `act`.
- Real auto PR: done — PR #897 fixed `anyio`, `authlib`, `certifi`, `PyJWT` across 11 manifests.

## Step 1: Local dry run

- Set `packages = ""` and `dry_run = true`.
- Run with `act`.
- Check the summary table: fixed, skipped, deferred.
- Confirm no branch and no PR.

## Step 2: Real auto PR

- Set `dry_run = false`.
- Run again.
- One branch and one PR are created.
- The PR fixes every safe critical package it found.
- Major bumps, no-patch packages, npm, and moved manifests are reported in the PR body.

## What the report will show

Example:

```text
Fixed: 230 critical
Report only:
  major bump: Pillow — 70
  no patch: chromadb — 20
  0.x constrained: uv — 8
  different ecosystem: npm — 5
  unmapped manifest: 28
Deferred by cap: N
```

The exact numbers can change as Dependabot rescans.

## Step 3: uv

`uv 0.11 → 0.13` needs `crewai-cli` upgraded too.

- Do a separate PR with `crewai-cli >= 1.15.31` and `uv >= 0.13.4`.
- Run full tests and e2e.
- Merge only if green.

## Step 4: npm

All 5 are in `docs/package-lock.json`.

```bash
cd docs
npm install
npm audit fix
npm run build
```

Open a separate npm PR.

## Step 5: Pillow and chromadb

- **Pillow major `12 → 13`:** report only. Never auto-fix. A human can decide later.
- **chromadb:** no patch. Wait for upstream or replace it in a separate product change.

## Step 6: Merge the workflow

After the critical PRs:

1. Merge the workflow file and docs.
2. Add auto mode to a weekly schedule.
3. Let it open one PR per week.
4. An admin reviews and merges each PR.

## Step 7: Verify after merge

1. Merge the PR.
2. Wait for Dependabot to rescan.
3. Run the workflow with `dry_run=true`.
4. Fixed packages should disappear from the same-major list.
5. Remaining alerts must have a reason in the report.

## Simple order

1. Dry-run auto-critical mode.
2. Real auto PR.
3. Merge.
4. uv PR.
5. npm PR.
6. Merge the workflow.
7. Add weekly auto mode.
8. Leave Pillow/chromadb for a human decision.

# Part 2 — #824: Dependency version handling — plan

## Status

- Written: `.github/workflows/dependency-update-copilot.yml` and `.github/scripts/dependency_caps.py`.
- One fully automatic weekly run: limits, updates, security fixes, fix loop, security-only fallback, npm, no-lock manifests, one PR.
- Covers everything the #659 workflow does (see the table in the design).
- Script tested end to end on a clone with the live alerts (see the spec).
- **Not run yet:** the workflow under `act` or on GitHub, the Copilot fix loop, the PR step, the full run time.

## Step 1: Small dry run

- `paths = examples/api/agui`, `dry_run = true`.
- Check: alerts read, `dry_run_ok`, the still-open list, no branch, no PR.

## Step 2: Small real PR

- Same `paths`, `dry_run = false`. Close the #659 PRs first (gate).
- Check the PR: only dependency files, template headings, marker, no attribution.

## Step 3: Fix loop

- Break a manifest on purpose; confirm Copilot fixes it, or the fallback keeps its security fixes.

## Step 4: Full run

- Empty `paths`. Measure run time against the 360-minute limit.

## Step 5: Merge and schedule

- Merge the workflow and the script to `develop`. Monday runs start by themselves.
- Confirm the `agent-kernel-ci[bot]` app can read Dependabot alerts (needs **Dependabot alerts: Read**).
- Remove the TEMPORARY `push` trigger.

## Step 6: Retire the #659 workflow

- After one clean weekly PR, delete `vulnerability-remediation-copilot.yml`.

## Open questions

- If the full run is longer than 360 minutes: split by folder into parallel jobs.
- Should libraries (`ak-py`) keep major limits? Set aside for now.
- A comment above a limit blocks normal raises but not security raises. Is that the rule the team wants?
