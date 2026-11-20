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
| Security review (PR #902) | Package code in `update` and `fix-1` could read the job's write token (from a parent process's environment) or replace the script that later steps and `finish` ran from the artifact. The App key was also passed, unused, to the e2e jobs | Jobs split: package code only where there is no write token; a checked patch is pushed by a job that runs no package code; the script always from the workflow's own commit; no App key in the e2e jobs; no `uv` cache; `packaging` pinned. `Verdict` no longer lets a round-2 "skipped" job hide a round-1 failure |
| 8, 9 (42166994310, 42195876212) | Run 8: `finish` crashed: `gh api` got HTTP 502 and the script parsed the error body as jobs. Run 9: round 1 `api/pydanticai` failed with `pydantic-ai-slim` 2.53 / `openai` 3 (`Event loop is closed`, held by the `*` hold); round 2 failed only on its turn-2 LLM answer, which also fails on other PRs (#603, #786). Unexplained, so no PR | `gh api` retried on 5xx, other errors stop; `judge-2`: Copilot labels round 2's unexplained failures flaky, dependency or unsure, with the same job's history on other branches (on run 9 it found `api/pydanticai` failing the same way on `feature/603`); flaky ones are accepted, others open a draft PR that lists them; timeouts after a round 1 pass are listed; App token permissions narrowed |
| `develop` after #919 (2026-11-12) | `chart-test` red on every branch: `package.sh` installs the exported lock with the branch wheel, and 28 locks carried `deprecated` 3.0.1 (created or re-locked after 3.0.0 shipped, while `agentkernel` had no limit on PyPI) against the `<2.0.0` #919 had capped in `ak-py`. `cap` never looks at other locks and `LockGuard` measures lines from each lock's own base, so nothing pulled them back; the e2e jobs re-resolve and never noticed | `deprecated` dropped from `ak-py` (unused since #248), which alone turns the smoke green: `uv export` pins `agentkernel` without extras, so `package.sh` meets only its base dependencies. Every lock check (`update` and each `hold`) pulls a lock carrying a repo package back inside that package's declared bounds, after `LockGuard` and before `uv sync`; a first version ran it once after `update`, which the next `hold` re-lock undid (PR #943 review). A drift the release rules out waits for the next release; a pull-back that breaks the version-line or security rule is listed instead. Not a PR gate, since a raised floor keeps locks outside until a release (`make lock-bounds-check` reports) |

## Next

1. One real run with the job split (Actions → Run workflow on this branch; close any open update PR first).
2. Merge to `develop`. Runs then start every second Monday; a run by hand is Actions → Run workflow.
3. Ask an admin to give the `agent-kernel-ci` app "Dependabot alerts: Read", then drop `DEPENDABOT_ALERTS_TOKEN`.
4. Check that `COPILOT_REQUEST_TOKEN` is a fine-grained token with only the Copilot permission, and that the e2e keys
   have low limits (see the accepted risks in the design).

## Follow-ups outside this work

- AK code fix so it works with `openai` 3 (one client per event loop).
- AK issue: the Pydantic AI adapter reads private `agent._instructions`.
- Flaky tests seen in the runs: `kind-smoke (dev)` (NATS), `broker-kafka`, answer-matching e2e tests.
- Report the `litellm` `mcp` import upstream.
