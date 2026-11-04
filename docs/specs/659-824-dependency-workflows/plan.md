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

- Written: the workflow, the script, `workflow_call` on `chart-test.yaml` and `code-quality.yml`, tracked locks for the 3 manifests that had none.
- Script tested locally on real manifests and live alerts (see the spec). `ruff` and `actionlint` pass.
- **Not run yet on GitHub in this form.**

## History

- **First full run (push trigger, 2026-11-04):** 31 minutes for 127 manifests. ak-py could not take `pydantic-ai-slim>=2.53` (security minimum; the adapter reads private `agent._instructions`), and the old rule stopped the whole run. → Blocked security fixes; one manifest's failure never stops the rest.
- **Second full run (PR #900):** the PR opened, but 19 CI jobs failed. 11: `openai` 2 → 3 (via `openai-agents` 0.24; `Event loop is closed` across event loops). 7: `litellm` 1.89.7+ imports `mcp.types.CacheableResult`. 1: `sandbox/broker-nats` pod never healthy, no error. The local checks could not see this: unit tests mock the model, examples need API keys. → Version lines; tests before the PR.
- **Same rules everywhere:** the 3 lock-free manifests got tracked locks (made against the local ak-py build, then `agentkernel` back to PyPI, so they start at the tested versions); no ak-py-specific code; every skip reported; unreadable alerts no longer stop the run.
- **Minimal rewrite:** one failure mechanism (Copilot names the package, the script holds it) for local and CI failures; Copilot edits nothing; tests run only in the gate. Removed: `lift`, the security-only fallback, the separate blocked step, the test baseline, the no-lock fixer, local pytest. Script 2,050 → about 1,080 lines; workflow 712 → about 360.

## Step 1: Real run

- Push the branch (the temporary push trigger starts a real run).
- Check: `update` pushes `deps/update-batch-<RUN_ID>`; `e2e-1`, `kind-1`, `lint-1` run on that commit; on a failure `fix-1` reads the logs and holds packages; `finish` opens the PR only when a round is green.
- Watch: the number of held packages, the run time, the API cost of two rounds.
- Close PR #900 once a green run replaces it.

## Step 2: Merge and schedule

- Remove the TEMPORARY `push` trigger. Merge to `develop`; Monday runs start by themselves.
- Ask an admin to give the `agent-kernel-ci` app "Dependabot alerts: Read", then drop `DEPENDABOT_ALERTS_TOKEN`.
- When `ANTHROPIC_API_KEY` lands in `test-reusable.yaml` (#721), pass it here too.

## Step 3: Retire the #659 workflow

- After one clean weekly PR, delete `vulnerability-remediation-copilot.yml`.

## Follow-ups outside this work

- AK code fix so it works with `openai` 3 (one client per event loop).
- AK issue: the Pydantic AI adapter reads private `agent._instructions`.
- Report the `litellm` `mcp` import upstream.

## Open questions

- Held-back majors: open one issue per held-back major so they are not forgotten?
- A failure with no real error blocks the PR. Accept, or allow a PR with that example listed as failing?
