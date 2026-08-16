# #590: Messaging integration e2e harness — Implementation Plan

Orders the build of the harness specified in [spec.md](spec.md). Each iteration leaves `e2e/` in a
runnable/testable state. No `ak-py/` changes — every step is under `e2e/`, `.github/workflows/`, or
docs.

## Iteration 1: Deployable app (Slack + Telegram)

- **Goal:** one OpenAI agent served over Slack + Telegram, runnable locally.
- **Files:** `e2e/app/app.py`, `e2e/app/config.yaml`, `e2e/app/pyproject.toml`,
  `e2e/app/build.sh`, `e2e/app/.env.example`, `e2e/app/.gitignore`.
- **Steps:**
  1. Register `general` agent via `OpenAIModule`; `main()` = `_maybe_start_gmail()` + `RESTAPI.run`
     (spec §App).
  2. `_handlers()` always-on Slack + Telegram; `config.yaml` routes both to `general` and sets
     `logging.ak.level: DEBUG` (spec §Config).
  3. Pin `agentkernel[api,openai,slack,telegram,gmail,whatsapp,messenger,instagram]` + `aiohttp`.
- **Verify:** `build.sh` succeeds; app boots locally and answers a Slack + Telegram message.

## Iteration 2: Terraform deployment to ECS

- **Goal:** long-lived ECS + API Gateway deployment reachable by webhook.
- **Files:** `e2e/app/deploy/{main,variables,outputs}.tf`, `terraform.tfvars`, `backend.tf`,
  `Dockerfile`, `deploy.sh`, `.terraform.lock.hcl`, `.gitignore`.
- **Steps:**
  1. `main.tf` wires the `yaalalabs/ak-containerized/aws` module with `gateway_endpoints`
     (Slack/Telegram POST) and the `TF_VAR_*` → env mapping (spec §Terraform).
  2. `outputs.tf` exposes the webhook URLs + `agent_invoke_url`; `backend.tf` remote state.
  3. `deploy.sh`: build package (`uv export --no-hashes --no-dev`), `terraform apply`,
     `wait_for_ecs_stable` with `read_tfvar`-derived cluster/region.
- **Verify:** `deploy.sh` reaches "ECS services are stable"; the Slack Events request URL verifies.

## Iteration 3: Read-back tests (Slack, Telegram) + one-time scripts

- **Goal:** automated full round-trip proof for the two always-on platforms.
- **Files:** `e2e/tests/conftest.py`, `test_slack.py`, `test_telegram.py`,
  `scripts/telegram_login.py`, `scripts/set_telegram_webhook.py`, `e2e/tests/pyproject.toml`.
- **Steps:**
  1. `require_env` skip helper + timeout constants (spec §Tests).
  2. Slack user-token round trip asserting `!= "Error handling your request."`; Telegram Telethon
     round trip asserting not in the fallback set.
  3. `telegram_login.py` (StringSession) + `set_telegram_webhook.py` (register URL/secret).
- **Verify:** `uv run pytest test_slack.py test_telegram.py` passes against the deployment.

## Iteration 4: Optional integrations (Gmail, WhatsApp, Messenger, Instagram)

- **Goal:** the remaining platforms activate when configured and degrade cleanly when not.
- **Files:** `e2e/app/app.py` (`_append_optional`, `_maybe_start_gmail`), `config.yaml`;
  `deploy/main.tf` + `variables.tf` (Meta GET+POST endpoints, optional TF vars default `""`);
  `e2e/tests/{test_gmail,test_whatsapp,test_messenger,test_instagram}.py`,
  `scripts/gmail_login.py`.
- **Steps:**
  1. Gmail background-thread polling guarded by try/except (spec §App); Meta handlers via
     `_append_optional` (credential-presence + construction try/except).
  2. Add the Meta GET (verification) + POST endpoints and every optional `AK_*` env var.
  3. Gmail read-back test; WhatsApp/Messenger/Instagram log-based tests gated on
     `E2E_*_AUTOMATED` (spec §Tests) — note the DEBUG-level dependency.
- **Verify:** with creds, Gmail round-trips; without, the app logs "disabled" and still serves
  Slack + Telegram. `E2E_WHATSAPP_AUTOMATED=1` log check passes against a manual send.

## Iteration 5: CI jobs (weekly + manual dispatch)

- **Goal:** deploy (opt-in) and test (scheduled/dispatch) jobs in the weekly workflow.
- **Files:** `.github/workflows/integration-test-weekly.yaml`.
- **Steps:**
  1. Add the `provision_e2e_messaging` dispatch input.
  2. `e2e-messaging-deploy`: build package, `terraform apply`, wait for ECS (cluster/region from
     `terraform.tfvars`), Terraform `1.14.3` (spec §CI).
  3. `e2e-messaging-test`: probe webhook health, re-register Telegram webhook, `uv run pytest -rs`.
- **Verify:** manual dispatch with `provision_e2e_messaging` deploys and the suite runs; a scheduled
  run tests the existing deployment without deploying.

## Iteration 6: Release-time version pin plumbing

- **Goal:** the published-`agentkernel` pin stays current without manual edits.
- **Files:** `.github/workflows/publish.yaml`, `.github/workflows/test.yaml`.
- **Steps:**
  1. `publish.yaml`: add an "Update e2e messaging harness" step
     (`update_examples_version.py --examples-dir e2e/app --skip-lock`) that commits `e2e/`
     (spec §Release-time version pin plumbing).
  2. `test.yaml` `update-lock-files`: add a step regenerating `e2e/app/uv.lock`
     (`--force-lock --examples-dir e2e/app`) and include it in the commit.
- **Verify:** `update_examples_version.py --examples-dir e2e/app --dry-run --version X.Y.Z` reports
  the pin bump; `test.yaml` dispatch with `update_example_locks` regenerates the lock.

## Iteration 7: Docs and skills sync

- **Files / surfaces to update (verified):**
  - `e2e/README.md` — full setup/deploy/run guide, env-var reference, published-wheel contract,
    per-platform automation ceilings. **Present.**
  - `AGENTS.md` repo map — add the `e2e/` line so agents/humans can find the tree. **Done** (repo
    map "Repo map" section).
  - `docs/specs/590-messaging-integration-e2e-tests/` — this design/spec/plan set. **This iteration.**
- **No update needed (verified):**
  - Dev skills under `.agents/skills/ak-dev-*` — the harness adds no core adapter/provider, so
    `ak-dev-architecture` / `ak-dev-new-messaging-integration` describe unchanged surfaces. Confirm
    with `ak-dev-sync-skills-from-branch` before merge.
  - Bundled end-user skills under `ak-py/src/agentkernel/skills/` — no package behaviour changed.
  - Docs website (`docs/docs/`) — the harness is contributor infrastructure, not an end-user
    feature; nothing to publish there. Confirm with `ak-dev-sync-docs-from-branch`.
- **Verify:** `ak-dev-sync-skills-from-branch` / `ak-dev-sync-docs-from-branch` report no further
  drift.
