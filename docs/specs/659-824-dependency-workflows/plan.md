# #659 and #824: Dependency update workflow — plan


## Status

- Written: the workflow, the script, `workflow_call` on `chart-test.yaml` and `code-quality.yml`, tracked locks for the 3 manifests that had none.
- Script tested locally on real manifests and live alerts (see the spec). `ruff` and `actionlint` pass.
- **Not run yet on GitHub in this form.**

## History

- **First full run (push trigger, 2026-11-04):** 31 minutes for 127 manifests. ak-py could not take `pydantic-ai-slim>=2.53` (security minimum; the adapter reads private `agent._instructions`), and the old rule stopped the whole run. → Blocked security fixes; one manifest's failure never stops the rest.
- **Second full run (PR #900):** the PR opened, but 19 CI jobs failed. 11: `openai` 2 → 3 (via `openai-agents` 0.24; `Event loop is closed` across event loops). 7: `litellm` imports `mcp.types.CacheableResult` (checked later: not in 1.89.x or 1.95.0, present in 1.108.0; CI got 1.108.0 because the examples resolve again against the local ak-py wheel). 1: `sandbox/broker-nats` pod never healthy, no error. The local checks could not see this: unit tests mock the model, examples need API keys. → Version lines; tests before the PR.
- **Same rules everywhere:** the 3 lock-free manifests got tracked locks (made against the local ak-py build, then `agentkernel` back to PyPI, so they start at the tested versions); no ak-py-specific code; every skip reported; unreadable alerts no longer stop the run.
- **Minimal rewrite:** one failure mechanism (Copilot names the package, the script holds it) for local and CI failures; Copilot edits nothing; tests run only in the gate. Removed: `lift`, the security-only fallback, the separate blocked step, the test baseline, the no-lock fixer, local pytest. Script 2,050 → about 1,080 lines; workflow 712 → about 360.
- **Third full run (41892521552):** Copilot named `litellm` and `pydantic-ai-slim`, `fix-1` pushed the holds, but round 2 was skipped: its jobs lacked `always()`, so GitHub's implied `success()` saw round 1's failure. Copilot also blocked the `litellm` security fix in 51 manifests on the prompt's own (wrong) example, although 1.95.0 works. Root cause: `secure` turned ak-py's `litellm~=1.89.2` into `<2.0.0`, so the local wheel let examples reach 1.108.0. → `always()` on round 2; `secure` keeps the `~=` width; `keep_minimum` holds a security package at its minimum; made-up prompt example; every two weeks.
- **Fourth full run (41964502523):** round 2 ran. Copilot checked the minimums itself and used `keep_minimum` (`litellm` 1.95.0 and 1.100.4), held `pydantic-ai-slim`, and wrote nothing for crewai, pydanticai and kind, which then passed in round 2 or failed on `develop` too (`kind-smoke (dev)`: 2 of the last 8 develop runs). Round 2 failed only on `kind-smoke (dev)` and `broker-kafka` (passed in round 1), so no PR. The PR body from `fix-1` also counted 4 files instead of 258 (plain `git diff` misses round 1's committed changes). → `verdict`: failures this update did not cause no longer block the PR; the report diffs against the base commit and lists every fixed alert.

## Step 1: Real run

- Push the branch (the temporary push trigger starts a real run).
- Check: `update` pushes `deps/update-batch-<RUN_ID>`; `e2e-1`, `kind-1`, `lint-1` run on that commit; on a failure `fix-1` reads the logs and holds packages; `finish` opens the PR only when a round is green.
- Watch: the number of held packages, the run time, the API cost of two rounds.
- Close PR #900 once a green run replaces it.

## Step 2: Merge and schedule

- Remove the TEMPORARY `push` trigger. Merge to `develop`; runs start by themselves every second Monday.
- Ask an admin to give the `agent-kernel-ci` app "Dependabot alerts: Read", then drop `DEPENDABOT_ALERTS_TOKEN`.
- When `ANTHROPIC_API_KEY` lands in `test-reusable.yaml` (#721), pass it here too.

## Follow-ups outside this work

- AK code fix so it works with `openai` 3 (one client per event loop).
- AK issue: the Pydantic AI adapter reads private `agent._instructions`.
- Report the `litellm` `mcp` import upstream.

## Open questions

- Held-back majors: open one issue per held-back major so they are not forgotten?
