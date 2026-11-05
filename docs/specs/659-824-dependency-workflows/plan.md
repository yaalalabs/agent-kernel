# #659 and #824: Dependency update workflow — plan

## Status

- Done: the workflow, the script, tracked locks for the 3 manifests that had none. The shared test workflows are
  unchanged.
- Tested with 7 real runs on GitHub (a temporary `push` trigger on the feature branch, now removed). The last one
  opened PR #908.

## Real runs

| Run | What happened | What changed |
|---|---|---|
| 1 (2026-11-04) | ak-py could not take `pydantic-ai-slim>=2.53`; the whole run stopped | Blocked security fixes; one manifest's failure never stops the rest |
| 2 (PR #900) | PR opened, 19 CI jobs failed: `openai` 2 → 3 (11), `litellm` imports a missing `mcp` name (7), `broker-nats` (1) | Version lines; tests before the PR |
| 3 (41892521552) | Round 2 skipped (no `always()`); `litellm` fix blocked in 51 manifests, copied from the prompt's example | `always()`; `~=` keeps its width; `keep_minimum`; made-up example |
| 4 (41964502523) | Round 2 failed only on `kind-smoke (dev)` (also flaky on develop) and `broker-kafka` (passed in round 1); no PR. PR body counted 4 files, not 258 | `verdict`; report diffs against the base commit |
| 5 (41972879075) | PR #901 opened; `cli/adk` (a wrong answer, passed in round 1) accepted. Fixed-alerts list repeated per severity. `aws-containerized/mcp/multi` kept `litellm` 1.108.0, the version that broke its tested twin | One line per package; integration tests after the PR; Copilot checks untested manifests with the same broken version |
| PR #902 (CodeQL) | 5 cache-poisoning alerts: `code-quality.yml` (new, from its `checkout_ref`) and `test-reusable.yaml` (old ones, shown because the file changed) | Kind and lint out of the gate (kind started after the PR, lint is a PR check); round 1's artifact deleted before round 2, so the shared workflows are unchanged |
| 6 (41986532730, PR #903) | Round 2 all green, PR opened; integration tests started, but without redeploying the Slack/Telegram app | `provision_e2e_messaging=true`; `ANTHROPIC_API_KEY` for the Claude examples (#833) |
| 7 (42020023574, PR #908) | Round 1: 6 failures. Copilot held `pydantic-ai-slim` and found the broken `litellm` in 5 manifests, including the untested `aws-containerized/mcp/multi`. Round 2 all green, PR opened, kind smoke and integration tests started, messaging tests passed on the redeployed app. The 5 after-PR failures were infra (`kreuzwerker/docker` provider download, a response-store race, `kind-smoke (eks)`) | None |

## Next

1. Merge to `develop`. Runs then start every second Monday; a run by hand is Actions → Run workflow.
2. Ask an admin to give the `agent-kernel-ci` app "Dependabot alerts: Read", then drop `DEPENDABOT_ALERTS_TOKEN`.

## Follow-ups outside this work

- AK code fix so it works with `openai` 3 (one client per event loop).
- AK issue: the Pydantic AI adapter reads private `agent._instructions`.
- Flaky tests seen in the runs: `kind-smoke (dev)` (NATS), `broker-kafka`, answer-matching e2e tests.
- Report the `litellm` `mcp` import upstream.
