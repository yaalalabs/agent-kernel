# #590: Messaging integration e2e harness — Implementation Spec

Detailed design for the `e2e/` harness whose requirements are in [design.md](design.md). The harness
is a self-contained tree — a deployable OpenAI-agent app, its Terraform, a pytest suite that drives
the deployed instance through real platform accounts, one-time setup scripts, and the CI wiring —
plus the release-time plumbing that keeps its published-`agentkernel` pin current. Nothing under
`ak-py/` changes; the harness consumes the published package.

## Design

### Directory layout

```
e2e/
  README.md                     One-time setup, per-platform provisioning, deploy, run, env reference
  app/                          Deployable agent app
    app.py                      Registers one OpenAI agent; RESTAPI.run([...handlers])
    config.yaml                 Per-platform agent routing; ak logger at DEBUG; gmail/telegram tuning
    pyproject.toml              agentkernel[...] pin + aiohttp; dev group (black/isort)
    uv.lock                     Pins the published agentkernel wheel that gets vendored
    build.sh                    uv venv + sync (local variant force-installs branch wheel)
    .env.example                Deployment credential template (gitignored .env is the real one)
    deploy/
      main.tf                   yaalalabs/ak-containerized/aws module + gateway_endpoints + env vars
      variables.tf              One TF var per credential; optional ones default "" (empty disables)
      outputs.tf                Per-platform webhook URLs + agent_invoke_url
      terraform.tfvars          region + product_alias/env_alias/module_name aliases
      backend.tf                Remote S3 state (shared dev bucket)
      Dockerfile                python:3.12-slim; runs `from app import main; main()`
      deploy.sh                 Local deploy: build package, terraform apply, wait for ECS stable
  tests/
    conftest.py                 REPLY_TIMEOUT/POLL constants + require_env() skip helper
    pyproject.toml, uv.lock     Test deps (pytest, slack-sdk, telethon, google-api, boto3, httpx)
    test_slack.py               Read-back round trip (user token → threaded bot reply)
    test_telegram.py            Read-back round trip (Telethon user session → bot reply)
    test_gmail.py               Read-back round trip (tester→bot email → poll thread for reply)
    test_whatsapp.py            Opt-in log-based check (send template → CloudWatch send-success)
    test_messenger.py           Opt-in log-based check of a recent human-triggered round trip
    test_instagram.py           Opt-in log-based check of a recent human-triggered round trip
    scripts/
      telegram_login.py         One-time: print Telethon StringSession
      set_telegram_webhook.py   One-time: register webhook URL (+ secret) via Bot API
      gmail_login.py            One-time: print base64 token.pickle per account
```

### App (`e2e/app/app.py`)

- `general` OpenAI agent (`gpt-4.1-mini`), one-sentence-reply instructions, registered via
  `OpenAIModule([general_agent])`.
- `main()` → `_maybe_start_gmail()` then `RESTAPI.run(_handlers())`.
- `_handlers()` returns `[AgentSlackRequestHandler(), AgentTelegramRequestHandler()]` (always on) plus
  each optional handler appended through `_append_optional(handlers, name, env_var, construct)`:
  1. If `env_var` (`AK_WHATSAPP__ACCESS_TOKEN` / `AK_MESSENGER__ACCESS_TOKEN` /
     `AK_INSTAGRAM__ACCESS_TOKEN`) is unset/empty → log "…not configured … disabled" and return.
  2. Else call `construct()` (a closure doing the lazy `from agentkernel.<platform> import …` and
     returning the handler) inside `try/except Exception` → append on success; on failure log
     `.exception("… failed to construct — continuing without it")` and continue.
  - Rule: the optional handlers each raise at construction unless **all** their required credentials
    are set (WhatsApp needs access_token + phone_number_id + verify_token), so the guard is
    credential-presence *plus* a construction try/except — a partial config must never crash the app.
- `_maybe_start_gmail()`:
  1. Return early (log "disabled") unless `AK_GMAIL__CLIENT_ID`, `AK_GMAIL__CLIENT_SECRET`, and
     `AK_GMAIL__TOKEN_B64` are all present.
  2. Inside `try/except Exception`: write the base64-decoded token to
     `Config.get().gmail.token_file`, construct `AgentGmailRequestHandler`, `authenticate()`, then
     start `asyncio.run(handler.start_polling())` in a daemon thread. On any failure log
     `.exception("Gmail integration failed to start — continuing without Gmail")` and return.
  - The try/except is the guard against the container crash-looping on an expired/revoked token
    (`gmail_chat.py` `authenticate()` calls `creds.refresh(...)`), keeping the always-on Slack +
    Telegram handlers up.

### Config (`e2e/app/config.yaml`)

- `logging.ak.level: DEBUG` — **load-bearing**: the log-based tests match the DEBUG-level
  `"Message sent successfully"` line, invisible at INFO.
- `<platform>.agent: "general"` routes every platform to the one agent.
- `telegram.api_version: "bot"`; `gmail.poll_interval: 15`, `gmail.label_filter: "INBOX"`.

### Terraform (`e2e/app/deploy/`)

- `main.tf`: `module "e2e_agents"` from `yaalalabs/ak-containerized/aws` (version pinned), `container_type = "ecs"`.
  - `gateway_endpoints`: `slack/events` (POST), `telegram/webhook` (POST), and for each Meta platform
    both a GET (Meta `hub.*` verification) and a POST (delivery): `whatsapp/webhook`,
    `messenger/webhook`, `instagram/webhook`. Each with `overwrite_path` to the handler route.
  - `rest_service.environment_variables`: `OPENAI_API_KEY`, `SLACK_BOT_TOKEN`,
    `SLACK_SIGNING_SECRET`, and the `AK_TELEGRAM__*` / `AK_GMAIL__*` / `AK_WHATSAPP__*` /
    `AK_MESSENGER__*` / `AK_INSTAGRAM__*` families, each fed from a TF variable.
- `variables.tf`: required (`openai_api_key`, `slack_bot_token`, `slack_signing_secret`,
  `telegram_bot_token`); every optional credential defaults to `""` — an empty value is what disables
  the corresponding integration in the app, so a minimal deploy is Slack + Telegram.
- `outputs.tf`: `agent_invoke_url` plus `slack_events_url`, `telegram_webhook_url`,
  `whatsapp_webhook_url`, `messenger_webhook_url`, `instagram_webhook_url` (built from the module's
  `api_gateway_id`/`api_gateway_stage`).
- `terraform.tfvars`: `region = "us-east-2"`, `product_alias = "ak-e2e"`, `env_alias = "dev"`,
  `module_name = "messaging"` → the ECS cluster name is `ak-e2e-dev-messaging`. Anything reading the
  cluster name derives it from these (see Behavioural changes #4).
- `backend.tf`: S3 remote state, key `e2e/messaging/terraform.tfstate` in the shared dev bucket.
- `Dockerfile`: `python:3.12-slim`, copies vendored `data/`, `CMD python -c "from app import main; main()"`.
- `deploy.sh`: loads gitignored `../.env`, maps `TF_VAR_*`, builds the deployment package
  (`uv export --no-hashes --no-dev` → vendored `dist/data`; the `local` arg force-installs the branch
  wheel from `../../ak-py/dist` and fails loudly if absent), `terraform init && apply`, then
  `wait_for_ecs_stable` (cluster/region derived via `read_tfvar`).

### Tests (`e2e/tests/`)

- `conftest.py`: `REPLY_TIMEOUT_SECONDS = 180`, `POLL_INTERVAL_SECONDS = 5`, and
  `require_env(*names) -> dict` which `pytest.skip`s listing any missing variable.
- Read-back tests — send a `uuid`-tagged prompt ("what is 2 + 2?"), poll to a deadline:
  - `test_slack.py`: `slack_sdk.WebClient(user_token).chat_postMessage`, then poll
    `conversations_replies` for a message whose `user == bot_user_id` (from
    `E2E_SLACK_BOT_USER_ID`, else `SLACK_BOT_TOKEN` → `auth.test`) and `ts != parent_ts`. Assert a
    reply exists, has visible text, and `!= "Error handling your request."`.
  - `test_telegram.py`: Telethon `TelegramClient(StringSession(...))` → `send_message`, poll
    `get_messages(min_id=sent.id)` for an inbound non-empty text. Assert a reply exists and is not in
    the three-string `TELEGRAM_ERROR_FALLBACKS` set.
  - `test_gmail.py`: build a `MIMEText` to `E2E_GMAIL_BOT_ADDRESS`, `users().messages().send`, poll
    `threads().get` for a message whose `From` contains the bot address. Assert a reply exists with a
    non-empty `snippet`. Timeout `300`s (mail is slower).
- Log-based tests — `boto3` `logs.filter_log_events` paginated by `nextToken`, `LOG_GROUP` from
  `E2E_LOG_GROUP` (default `/aws/ecs/ak-e2e-dev-messaging-service/ak-e2e-dev-messaging-app`), region
  from `E2E_AWS_REGION` (default `us-east-2`):
  - `test_whatsapp.py`: skip unless `E2E_WHATSAPP_AUTOMATED`; send a `hello_world` template from the
    sender number via Graph API `v24.0`; poll for a `"Message sent successfully"` event containing
    the sender `wa_id`; then assert **no** `"Error handling message"` event (the error fallback also
    "sends successfully", so the error line is what catches it).
  - `test_messenger.py` / `test_instagram.py`: skip unless `E2E_MESSENGER_AUTOMATED` /
    `E2E_INSTAGRAM_AUTOMATED`; scan a lookback window (default 300s) for a send-success line **scoped
    by logger name** (`'"ak.api.messenger" "Message sent successfully"'`) and assert no matching
    `"Error handling message"`.

### Setup scripts (`e2e/tests/scripts/`)

- `telegram_login.py`: interactive Telethon login (`E2E_TELEGRAM_API_ID`/`_API_HASH`), prints
  `client.session.save()` for `E2E_TELEGRAM_SESSION`.
- `set_telegram_webhook.py`: `--url` + `E2E_TELEGRAM_BOT_TOKEN` (+ optional
  `E2E_TELEGRAM_WEBHOOK_SECRET`) → Bot API `setWebhook` (`drop_pending_updates: true`), prints
  `getWebhookInfo`.
- `gmail_login.py`: `InstalledAppFlow.run_local_server` with the three Gmail scopes
  (`readonly`, `send`, `modify` — matching the handler), prints base64 `pickle.dumps(creds)`.

### CI (`.github/workflows/integration-test-weekly.yaml`)

- Dispatch input `provision_e2e_messaging` (default false) gates deployment.
- `e2e-messaging-deploy` (`if: workflow_dispatch && inputs.provision_e2e_messaging`): install `uv`,
  configure AWS creds (`us-east-2`), Terraform `1.14.3` (`terraform_wrapper: false`); build the
  package under `e2e/app` (`uv venv`; `uv export --no-hashes --no-dev`; vendor into `dist/data`; copy
  `app.py`/`config.yaml`/`Dockerfile`); `terraform init/apply` in `e2e/app/deploy` with every
  `TF_VAR_*` from `E2E_*` secrets/variables; wait for ECS stable with cluster/region **derived from
  `terraform.tfvars`** via an inline `read_tfvar`.
- `e2e-messaging-test` (`needs: [e2e-messaging-deploy]`, `if: always() && (deploy success or
  skipped)`): Terraform `1.14.3`; `terraform output -raw telegram_webhook_url` and probe it (HTTP
  200/403 healthy, 500/503 → fail with a redeploy hint); `uv sync`; re-register the Telegram webhook;
  `uv run pytest -v -rs` with the `E2E_*` secrets/variables. Scheduled runs skip deploy and test the
  live deployment as-is.

### Release-time version pin plumbing

- `.github/workflows/publish.yaml` (production only): a new step runs
  `scripts/update_examples_version.py --version <new> --examples-dir e2e/app --skip-lock`, then
  commits/pushes `e2e/` if changed — mirroring the existing `examples/` bump. `--skip-lock` is
  deliberate: the freshly published version may not be resolvable on PyPI yet.
- `.github/workflows/test.yaml` `update-lock-files` job: a new step runs
  `scripts/update_examples_version.py --force-lock --examples-dir e2e/app`, and the commit step adds
  `e2e/app/uv.lock` alongside `examples/**/uv.lock`. This regenerates the lock once the new version is
  available — the decoupling the maintainer asked for.
- `scripts/update_examples_version.py` is reused unchanged: it `rglob`s `pyproject.toml` under the
  given dir and regex-bumps the `agentkernel[...]>=` pin, so `--examples-dir e2e/app` targets exactly
  `e2e/app/pyproject.toml`.

## Config changes

- No `AKConfig` / `core/config.py` change. The app reads only existing config keys
  (`slack`/`telegram`/`gmail`/`whatsapp`/`messenger`/`instagram`, `logging`) and existing `AK_*` env
  vars. `e2e/app/config.yaml` and the `TF_VAR_*` → env mapping in `main.tf` are new files, not
  changes to shared config.

## Behavioural changes

All behaviour here is new (greenfield harness) except the four items below, which are decisions where
an obvious alternative exists — each is intentional:

1. **Optional handlers degrade instead of crashing.** A partial/broken WhatsApp/Messenger/Instagram
   config logs and is skipped (`_append_optional` try/except), rather than propagating the handler's
   construction error and aborting `RESTAPI.run()`. Justification: the optional integrations must
   never take the always-on Slack/Telegram down.
2. **Gmail auth failure degrades instead of crash-looping.** `_maybe_start_gmail`'s
   construct/authenticate/start is wrapped in try/except. Justification: an expired/revoked token (or
   the 7-day "Testing" expiry) otherwise crash-loops the container.
3. **The deployment runs the published wheel, not the branch.** `uv.lock` pins the PyPI
   `agentkernel`; the deploy vendors it. Justification: the harness validates the *released* package's
   integrations; branch validation is the explicit `deploy.sh local` path. Documented in
   `e2e/README.md`.
4. **Cluster name/region are derived from `terraform.tfvars`, not hardcoded.** The CI wait step and
   `deploy.sh` both derive `ak-e2e-dev-messaging` from `product_alias`/`env_alias`/`module_name`.
   Justification: the README invites editing those aliases; a hardcoded name would silently break.
   (The test-side `E2E_LOG_GROUP` default still embeds the name but is overridable via env.)

**Non-changes:** no `ak-py/` source, no `AKConfig` fields, no existing workflow job (only new jobs /
new steps added), no change to `scripts/update_examples_version.py` behaviour, no change to the
shared state bucket convention (`backend.tf` matches `agent/deploy/backend.tf`).

## Error handling

- **App startup** — optional-integration and Gmail failures are caught and logged; Slack + Telegram
  always start. A missing *required* credential (Slack/Telegram/OpenAI) is a genuine
  misconfiguration and is allowed to fail loudly at handler construction.
- **Tests** — missing credentials → `pytest.skip` (via `require_env`), never a failure, so partial
  credential sets are first-class. A sent message with no reply within the deadline → assertion
  failure naming the timeout and (for log tests) the log group. A reply equal to a known
  error-fallback string, or a logged `"Error handling message"`, → assertion failure (transport OK,
  agent run failed).
- **CI** — the health probe fails the test job on HTTP 500/503 (no healthy task) with a
  redeploy hint; a non-healthy service is surfaced, not silently tested.
- **Local deploy** — `deploy.sh local` no longer swallows the branch-wheel reinstall failure
  (`set -e` aborts), so a missing `../../ak-py/dist` wheel fails loudly instead of shipping a mixed
  dependency set.

## Testing

This change **is** the test harness; its "tests" are the seven pytest files above, exercised against
a live deployment. There is no `ak-py` unit-test surface to add.

- Run locally (one platform at a time; missing-cred platforms skip):
  ```bash
  cd e2e/tests && uv sync && uv run pytest -v -rs
  ```
- Full round-trip proof is only available for Slack / Telegram / Gmail; WhatsApp / Messenger /
  Instagram are log-based and opt-in (see design.md "Verification depth").
- The deployment itself is validated by the CI `e2e-messaging-deploy` job (Terraform apply + ECS
  stabilize) and the `e2e-messaging-test` health probe before the suite runs.
- The release plumbing is exercised by the existing `publish.yaml` / `test.yaml` flows; the added
  steps reuse the already-tested `update_examples_version.py`.
