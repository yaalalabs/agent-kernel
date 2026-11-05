# #659 and #824: Dependency update workflow — plan

## Status

- Done: the workflow, the script, `workflow_call` on `chart-test.yaml` and `code-quality.yml`, tracked locks for
  the 3 manifests that had none.
- Tested with real runs on GitHub (the temporary `push` trigger). The fifth run opened PR #901.

## Real runs

| Run | What happened | What changed |
|---|---|---|
| 1 (2026-11-04) | ak-py could not take `pydantic-ai-slim>=2.53`; the whole run stopped | Blocked security fixes; one manifest's failure never stops the rest |
| 2 (PR #900) | PR opened, 19 CI jobs failed: `openai` 2 → 3 (11), `litellm` imports a missing `mcp` name (7), `broker-nats` (1) | Version lines; tests before the PR |
| 3 (41892521552) | Round 2 skipped (no `always()`); `litellm` fix blocked in 51 manifests, copied from the prompt's example | `always()`; `~=` keeps its width; `keep_minimum`; made-up example |
| 4 (41964502523) | Round 2 failed only on `kind-smoke (dev)` (also flaky on develop) and `broker-kafka` (passed in round 1); no PR. PR body counted 4 files, not 258 | `verdict`; report diffs against the base commit |
| 5 (41972879075) | PR #901 opened; `cli/adk` (a wrong answer, passed in round 1) accepted. Fixed-alerts list repeated per severity. `aws-containerized/mcp/multi` kept `litellm` 1.108.0, the version that broke its tested twin | One line per package; integration tests after the PR; Copilot checks untested manifests with the same broken version |

## Next

1. One more real run with the latest changes (close PR #901 first: only one update PR at a time).
2. Remove the TEMPORARY `push` trigger and merge to `develop`. Runs then start every second Monday.
3. Ask an admin to give the `agent-kernel-ci` app "Dependabot alerts: Read", then drop `DEPENDABOT_ALERTS_TOKEN`.
4. When `ANTHROPIC_API_KEY` lands in `test-reusable.yaml` (#721), pass it here too.

## Follow-ups outside this work

- AK code fix so it works with `openai` 3 (one client per event loop).
- AK issue: the Pydantic AI adapter reads private `agent._instructions`.
- Flaky tests seen in the runs: `kind-smoke (dev)` (NATS), `broker-kafka`, answer-matching e2e tests.
- Report the `litellm` `mcp` import upstream.
