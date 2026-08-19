# Messaging Integration E2E Test Harness

True end-to-end tests for Agent Kernel's messaging integrations against **real platform
accounts**: a real message is sent by a real user account, delivered by the platform's
webhook to a **deployed ECS instance**, processed by a real OpenAI agent, and the real
reply is read back from the platform. This covers the full transport layer (API Gateway,
webhook routing, Slack signature verification, Telegram secret token) that in-process
tests cannot.

Current coverage: **Slack**, **Telegram**, **Gmail**, **WhatsApp**, **Messenger**,
**Instagram**, and **Microsoft Teams** — every messaging platform Agent Kernel can
construct today.

Verification depth differs by platform:
- **Slack / Telegram / Gmail** — read the agent's reply back from the platform (full
  round-trip proof), fully automated in CI.
- **Teams** — driven through the bot's **Direct Line** channel rather than the Teams
  client (there is no API to post into Teams as a user). Same Azure Bot, same deployed
  webhook, so it proves the Bot Framework transport and the handler end to end.
- **WhatsApp** — no read-back API; verified via CloudWatch logs. Automated test is opt-in
  (`E2E_WHATSAPP_AUTOMATED=1`) and needs a production sender number; otherwise manual.
- **Messenger / Instagram** — cannot be automated at all (no API to message a Page/account
  as a user); manual verification only, with a log-based opt-in check
  (`E2E_MESSENGER_AUTOMATED=1` / `E2E_INSTAGRAM_AUTOMATED=1`).

## Layout

```
e2e/
  app/                  Deployable agent app: one OpenAI agent + Slack + Telegram handlers
    deploy/             Terraform (yaalalabs/ak-containerized/aws) + Dockerfile + deploy.sh
  tests/                pytest harness that drives the deployed instance
    scripts/            One-time helpers (Telegram login, webhook registration)
```

The deployment is **one-time / long-lived**: deploy once, then run the tests on demand as
often as needed.

## One-time setup

### 1. Slack

1. Create a Slack app in the test workspace (<https://api.slack.com/apps>).
   - Bot token scopes: `chat:write`, `channels:history`, `files:read`.
   - Install to the workspace; note the **bot token** (`xoxb-...`) and **signing secret**.
2. Create a dedicated test channel and `/invite` the bot into it. Note the channel ID.
3. Create a **user token** for the tester account: easiest is to add user token scopes
   (`chat:write`, `channels:history`) to the same app and reinstall; note the `xoxp-...`
   token. The sender must be a user token — the Slack handler ignores bot-authored
   messages, so a second bot cannot drive the test.
4. After deploying (step 3 below), set the app's **Event Subscriptions**:
   - Request URL: the `slack_events_url` terraform output. Slack's URL verification
     challenge is answered automatically by the deployed handler.
   - Subscribe to bot event `message.channels`.

### 2. Telegram

1. Create a bot with [@BotFather](https://t.me/BotFather); note the **bot token** and
   the bot's **username**.
2. Get MTProto API credentials for the tester **user** account at
   <https://my.telegram.org> (API development tools): **api_id** and **api_hash**.
   A real user account is required — Telegram bots cannot message other bots.
3. Generate the tester's session string (one time, interactive):

   ```bash
   cd e2e/tests
   uv sync
   E2E_TELEGRAM_API_ID=... E2E_TELEGRAM_API_HASH=... uv run python scripts/telegram_login.py
   ```

   Export the printed string as `E2E_TELEGRAM_SESSION`. Treat it like a password.
4. Open a chat with the bot from the tester account and send `/start` once (Telegram
   only lets bots message users who initiated a conversation).

### 2b. Gmail (optional)

Needs **two** Gmail accounts: the bot account (the deployment polls its inbox and
replies) and a tester account (the test sends from it and reads the reply). Send-to-self
cannot work — the bot would reply to its own replies in a loop.

1. In [Google Cloud console](https://console.cloud.google.com): create a project, enable
   the **Gmail API**, configure the OAuth consent screen, and create an OAuth client of
   type **Desktop app** — note the client ID and secret.
   - Add both Gmail addresses as test users, and **set the consent screen's publishing
     status to "In production"** — tokens minted while in "Testing" status expire after
     7 days, which silently kills the deployment's Gmail auth.
2. Generate a token for each account (browser opens — pick the right account each time):

   ```bash
   cd e2e/tests
   E2E_GMAIL_CLIENT_ID=... E2E_GMAIL_CLIENT_SECRET=... uv run python scripts/gmail_login.py
   ```

   - Bot account's output → `GMAIL_TOKEN_B64` in `app/.env` (and CI secret
     `E2E_GMAIL_BOT_TOKEN_B64`)
   - Tester account's output → `E2E_GMAIL_TESTER_TOKEN_B64` (test-side env / CI secret)
3. Set `GMAIL_SENDER_FILTER` to the tester's address so the bot ignores stray mail, and
   use a fresh/dedicated bot inbox — on startup the handler processes **all unread
   INBOX mail** passing the filter.

The Gmail integration is optional: when its variables are empty the deployed app runs
Slack + Telegram only.

### 2c. WhatsApp (optional)

Needs **two Meta developer apps**, each with the WhatsApp product and its own test
business number: one is the bot, the other is the sender. They must be separate apps —
the handler replies to every message its app's webhook delivers, so if both numbers
shared one app the bot would answer its own replies in a loop.

1. Create both apps at <https://developers.facebook.com> → Add product **WhatsApp**.
   Each gets a free test number; note each app's **access token** and **phone number ID**
   (WhatsApp → API Setup).
2. Register each number in the *other* app's allowed-recipients list (API Setup → "To"
   dropdown → Manage phone number list) — test numbers can only message registered
   recipients.
3. Choose a **verify token** (any random string) for the bot app.
4. Fill `app/.env` (`WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`,
   `WHATSAPP_VERIFY_TOKEN`, optionally `WHATSAPP_APP_SECRET`) with the **bot** app's
   values and redeploy.
5. Register the webhook in the **bot** app: WhatsApp → Configuration → Webhook →
   Callback URL = the `whatsapp_webhook_url` terraform output, Verify token = the value
   from step 3 → Verify and save → subscribe to the **messages** webhook field.
   Do **not** configure a webhook on the sender app.
6. Heads-up: Meta test-number access tokens are temporary (~24h) by default — for a
   long-lived deployment generate a system-user token or refresh before runs.

**Automation ceiling (important):** two WhatsApp Cloud API *test* numbers cannot message
each other — the bot number can't be verified into the sender's allowed-recipient list
because the verification OTP is undeliverable to a test number (confirmed: sender→bot
always returns error `131030`). So `test_whatsapp.py` **skips by default** and only runs
when `E2E_WHATSAPP_AUTOMATED=1`, which requires a **production** sender number
(business-verified + payment method). The deployment and handler are otherwise verified
**manually**:

1. Add your real phone to the **bot** app's recipient allowlist (real OTP, arrives in
   your WhatsApp app).
2. Register the bot webhook (done via the Graph API — see the WhatsApp section of the
   webhook step below).
3. From your phone, message the bot number (e.g. "Hello"). Watch the deployment logs:
   ```bash
   aws logs tail /aws/ecs/ak-e2e-dev-messaging-service/ak-e2e-dev-messaging-app \
     --region us-east-2 --since 5m | grep -i whatsapp
   ```
   You should see the inbound message, the agent response, and a successful send back —
   and receive the reply on your phone.

Use a permanent **system-user** access token (Business Settings → System users), not the
dashboard's temporary 24h token, or the deployment's WhatsApp auth dies within a day.

### 2d. Messenger (optional)

Needs a Facebook **Page** and a Meta app with the **Messenger** product. There is no way
to send a message to a Page as a user programmatically, so this is manual-verify only —
you DM the Page from your own Facebook account and confirm the bot replies.

1. Create/choose a Facebook Page for the bot.
2. In a Meta app (the WhatsApp bot app can be reused, or a fresh one) → Add product
   **Messenger** → **Generate** a **Page access token** for that Page.
3. Choose a **verify token** (any random string).
4. Fill `app/.env` (`MESSENGER_ACCESS_TOKEN` = Page token, `MESSENGER_VERIFY_TOKEN`,
   optionally `MESSENGER_APP_SECRET`) and redeploy.
5. Register the webhook: Messenger → Settings → Webhooks → Callback URL =
   `messenger_webhook_url` terraform output, Verify token = step 3, subscribe the Page to
   the **messages** field.
6. Verify manually: from your personal Facebook account, send the Page a message. Watch
   the logs — you should see the inbound message, agent response, and a successful send,
   and receive the reply in Messenger:
   ```bash
   aws logs tail /aws/ecs/ak-e2e-dev-messaging-service/ak-e2e-dev-messaging-app \
     --region us-east-2 --since 5m | grep -i messenger
   ```

CI: add secrets `E2E_MESSENGER_ACCESS_TOKEN`, `E2E_MESSENGER_VERIFY_TOKEN`,
`E2E_MESSENGER_APP_SECRET`. The automated test skips unless `E2E_MESSENGER_AUTOMATED=1`
(and even then it only confirms a *recent human-triggered* round trip via logs).

### 2e. Instagram (optional)

Needs an **Instagram Business/Creator account** and a Meta app with the **Instagram**
product (Business Login for Instagram). Like Messenger, there is no API to DM an account
as a user, so this is manual-verify only.

1. Convert the bot's Instagram account to a **Business** or **Creator** account (in the
   Instagram app → Settings → Account type).
2. In a Meta app (reuse the WhatsApp/Messenger bot app or a fresh one) → Add product
   **Instagram** → set up **API with Instagram login** → connect the IG account and
   **generate an Instagram access token**. Note the token and the **IG account ID**.
3. Choose a **verify token** (any random string).
4. Fill `app/.env` (`INSTAGRAM_ACCESS_TOKEN`, `INSTAGRAM_VERIFY_TOKEN`,
   `INSTAGRAM_ACCOUNT_ID`, optionally `INSTAGRAM_APP_SECRET`) and redeploy.
5. Register the webhook: Instagram → webhooks → Callback URL = `instagram_webhook_url`
   terraform output, Verify token = step 3, subscribe to the **messages** field. (I can
   also register this via the Graph API, same as WhatsApp/Messenger.)
6. Verify manually: from a *different* Instagram account, DM the bot account. Watch the
   logs:
   ```bash
   aws logs tail /aws/ecs/ak-e2e-dev-messaging-service/ak-e2e-dev-messaging-app \
     --region us-east-2 --since 5m | grep -i instagram
   ```

CI: add secrets `E2E_INSTAGRAM_ACCESS_TOKEN`, `E2E_INSTAGRAM_VERIFY_TOKEN`,
`E2E_INSTAGRAM_APP_SECRET`; variable `E2E_INSTAGRAM_ACCOUNT_ID`. The automated test skips
unless `E2E_INSTAGRAM_AUTOMATED=1` (and even then only confirms a *recent human-triggered*
round trip via logs).

### 2f. Microsoft Teams (optional)

Needs an **Azure Bot** resource backed by an Entra ID app registration. There is no API
to post into a Teams channel *as a user*, so the automated test talks to the same bot
over its **Direct Line** channel — the activity takes the identical path (Bot Framework
auth → the deployed `/teams/messages` endpoint → the handler → `continue_conversation`
reply), so a Direct Line round trip proves the integration. The **Teams** channel is
added alongside it for manual verification from the real client.

1. Create the app registration and the bot (Azure portal → **Azure Bot**, or `az`):
   - The live e2e bot (`ak-e2e-teams-bot`) is app type **Single Tenant**, so
     `TEAMS_TENANT_ID` must be its own tenant; a multi-tenant registration works too, and
     then the value stays empty. Note the **App ID (client ID)**, generate a **client
     secret**, and note the **tenant ID**.
   - If you create the registration with `az ad app create` or the Graph API rather than
     the portal, **create its service principal too** (`az ad sp create --id <app-id>`).
     Without it the webhook still answers 200 and every reply dies with `AADSTS7000229`.
2. Set the bot's **messaging endpoint** to the `teams_messages_url` terraform output
   (`.../teams/messages`).
3. Add channels: **Direct Line** (copy one of its **secret keys** → the test's
   `E2E_TEAMS_DIRECTLINE_SECRET`) and **Microsoft Teams**.
4. Fill `app/.env` (`TEAMS_APP_ID`, `TEAMS_APP_PASSWORD`, optionally `TEAMS_TENANT_ID`)
   and redeploy. The handler is only mounted when `AK_TEAMS__APP_ID` is set.
5. Verify manually in Teams: from the bot's Azure Bot blade use **Open in Teams**, or
   sideload a manifest whose `botId` is the app ID, then message the bot.
   ```bash
   aws logs tail /aws/ecs/ak-e2e-dev-messaging-service/ak-e2e-dev-messaging-app \
     --region us-east-2 --since 5m | grep -i teams
   ```

CI: add secrets `E2E_TEAMS_APP_ID`, `E2E_TEAMS_APP_PASSWORD`,
`E2E_TEAMS_DIRECTLINE_SECRET`; variable `E2E_TEAMS_TENANT_ID` — set, since the bot is
single-tenant. `test_teams.py` skips when the Direct Line secret is absent.

Attachments are **not** covered by the automated test: Direct Line serves uploads from
different hosts than Teams' `smba.trafficmanager.net` / SharePoint, so attachment
download is exercised by the unit tests and by manual Teams verification instead.

### 3. Deploy to AWS ECS

The primary deploy path is the `e2e-messaging-deploy` job in the **Weekly Integration
Tests** workflow (`.github/workflows/integration-test-weekly.yaml`) — dispatch it
manually with the `provision_e2e_messaging` input enabled. It must run on a Linux
runner: the
container image vendors Python dependencies at build time, and building from a Mac ships
macOS native extensions that crash the linux/amd64 container.

The job builds `ak-py` from the checked-out revision and installs that wheel over the
released `agentkernel` the lock file resolves, so the deployment always exercises the
branch's code — an integration added on a branch is not on PyPI yet. Locally, `app/build.sh
local` does the same thing. Re-provision whenever the integration code changes; a run
without `provision_e2e_messaging` tests whatever is already deployed.

One-time: add these secrets to the repo's `ci-tests` environment (Settings → Environments
→ ci-tests): `E2E_SLACK_BOT_TOKEN`, `E2E_SLACK_SIGNING_SECRET`, `E2E_TELEGRAM_BOT_TOKEN`,
`E2E_TELEGRAM_WEBHOOK_SECRET` (`OPENAI_API_KEY` already exists). The job applies the
terraform in place (the deployment is long-lived — no destroy step, so the API Gateway
URL and the Slack Event Subscriptions registration stay stable), waits for the ECS
service to stabilize, probes the deployed webhook endpoint, re-registers the Telegram
webhook, and runs the test suite.

Terraform state is remote (`backend.tf` → the shared dev state bucket), so local applies
with `deploy/deploy.sh` (+ `app/.env`, see `.env.example`) operate on the same deployment
— but only use that from a Linux machine, for the wheel reason above.

Adjust `terraform.tfvars` (region, aliases) before the first apply if needed. To use an
existing VPC, set `vpc_id` and `private_subnet_ids`; otherwise the module creates one.

### 4. Register the webhooks

- **Slack**: paste the `slack_events_url` output into the app's Event Subscriptions
  request URL (step 1.4).
- **Telegram**:

  ```bash
  cd e2e/tests
  export E2E_TELEGRAM_BOT_TOKEN=123456:ABC...
  export E2E_TELEGRAM_WEBHOOK_SECRET=...   # same value as TELEGRAM_WEBHOOK_SECRET in app/.env
  uv run python scripts/set_telegram_webhook.py \
    --url "$(terraform -chdir=../app/deploy output -raw telegram_webhook_url)"
  ```

## Running the tests

**Via GitHub Actions (default):** the `e2e-messaging-test` job in the Weekly Integration
Tests workflow probes the deployment, registers the Telegram webhook, and runs the full
pytest suite — weekly on schedule, or on demand via workflow_dispatch. Deployment is a
separate, optional job (`e2e-messaging-deploy`) that runs only when the workflow is
dispatched with `provision_e2e_messaging` enabled; scheduled runs test the existing
deployment as-is. The tests need these in the `ci-tests` environment, in addition to the
deploy secrets above: secrets `E2E_SLACK_USER_TOKEN`, `E2E_TELEGRAM_API_ID`,
`E2E_TELEGRAM_API_HASH`, `E2E_TELEGRAM_SESSION`; variables `E2E_SLACK_CHANNEL_ID`,
`E2E_TELEGRAM_BOT_USERNAME`.

**Locally:**

```bash
cd e2e/tests
uv sync

# Slack
export E2E_SLACK_USER_TOKEN=xoxp-...      # tester user token (sender + reader)
export E2E_SLACK_CHANNEL_ID=C0123456789   # test channel the bot is a member of
export SLACK_BOT_TOKEN=xoxb-...           # or E2E_SLACK_BOT_USER_ID=U... to skip auth.test

# Telegram
export E2E_TELEGRAM_API_ID=...
export E2E_TELEGRAM_API_HASH=...
export E2E_TELEGRAM_SESSION=...           # from scripts/telegram_login.py
export E2E_TELEGRAM_BOT_USERNAME=@your_e2e_bot

uv run pytest -v
```

Tests whose environment variables are missing are **skipped**, so you can run one
platform at a time. Each test sends a uniquely-tagged message and polls up to 3 minutes
for the agent's reply.

## What is asserted

First cut: *the integration works* — the bot replied with something. Specifically:

- a reply from the bot arrived (Slack: threaded under the test message; Telegram: in the
  tester–bot chat), and
- the reply is not one of the handlers' known error-fallback messages (e.g. Slack's
  `"Error handling your request."`), which would mean the transport worked but the agent
  run failed.

Response *content* is deliberately not asserted.

## Environment variable reference

Deployment variables live in `e2e/app/.env` (see `.env.example`); test variables are plain
environment variables.

| Variable | Used by | Purpose |
| --- | --- | --- |
| `OPENAI_API_KEY` | deploy (`app/.env`) | OpenAI key for the deployed agent |
| `SLACK_BOT_TOKEN` / `SLACK_SIGNING_SECRET` | deploy (`app/.env`) | Slack app credentials for the deployed handler |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_WEBHOOK_SECRET` | deploy (`app/.env`) | Telegram bot credentials for the deployed handler |
| `E2E_SLACK_USER_TOKEN` | tests | Tester user token (`xoxp-`), sends and reads messages |
| `E2E_SLACK_CHANNEL_ID` | tests | Test channel ID |
| `SLACK_BOT_TOKEN` or `E2E_SLACK_BOT_USER_ID` | tests | Identifies which replies came from the bot |
| `E2E_TELEGRAM_API_ID` / `E2E_TELEGRAM_API_HASH` | tests | MTProto app credentials of the tester account |
| `E2E_TELEGRAM_SESSION` | tests | Telethon StringSession of the tester account |
| `E2E_TELEGRAM_BOT_USERNAME` | tests | Deployed bot's username |
| `E2E_TELEGRAM_BOT_TOKEN` / `E2E_TELEGRAM_WEBHOOK_SECRET` | webhook script | One-time Telegram webhook registration |
| `GMAIL_CLIENT_ID` / `GMAIL_CLIENT_SECRET` / `GMAIL_TOKEN_B64` / `GMAIL_SENDER_FILTER` | deploy (`app/.env`) | Bot Gmail account OAuth + sender allowlist (CI: `E2E_GMAIL_CLIENT_ID`, `E2E_GMAIL_CLIENT_SECRET`, `E2E_GMAIL_BOT_TOKEN_B64`, variable `E2E_GMAIL_TESTER_ADDRESS`) |
| `E2E_GMAIL_TESTER_TOKEN_B64` | tests | Tester Gmail account token (base64 pickle) |
| `E2E_GMAIL_BOT_ADDRESS` | tests | Bot Gmail address the deployment polls (CI: variable) |
| `WHATSAPP_ACCESS_TOKEN` / `WHATSAPP_PHONE_NUMBER_ID` / `WHATSAPP_VERIFY_TOKEN` / `WHATSAPP_APP_SECRET` | deploy (`app/.env`) | Bot Meta app credentials (CI: `E2E_WHATSAPP_BOT_ACCESS_TOKEN`, `E2E_WHATSAPP_VERIFY_TOKEN`, `E2E_WHATSAPP_APP_SECRET` secrets; `E2E_WHATSAPP_BOT_PHONE_NUMBER_ID` variable) |
| `E2E_WHATSAPP_SENDER_ACCESS_TOKEN` | tests | Sender Meta app Cloud API token (CI: secret) |
| `E2E_WHATSAPP_SENDER_PHONE_NUMBER_ID` / `E2E_WHATSAPP_BOT_NUMBER` / `E2E_WHATSAPP_SENDER_NUMBER` | tests | Sender phone number ID + both numbers in digits-only international format (CI: variables) |
| `MESSENGER_ACCESS_TOKEN` / `MESSENGER_VERIFY_TOKEN` / `MESSENGER_APP_SECRET` | deploy (`app/.env`) | Bot Page access token + webhook verify token + app secret (CI: `E2E_MESSENGER_*` secrets) |
| `E2E_MESSENGER_AUTOMATED` | tests | Set to `1` to run the Messenger log-based check (default: skip) |
| `INSTAGRAM_ACCESS_TOKEN` / `INSTAGRAM_VERIFY_TOKEN` / `INSTAGRAM_APP_SECRET` / `INSTAGRAM_ACCOUNT_ID` | deploy (`app/.env`) | IG business token + verify token + app secret + account ID (CI: `E2E_INSTAGRAM_*` secrets/variable) |
| `E2E_INSTAGRAM_AUTOMATED` | tests | Set to `1` to run the Instagram log-based check (default: skip) |
| `TEAMS_APP_ID` / `TEAMS_APP_PASSWORD` / `TEAMS_TENANT_ID` | deploy (`app/.env`) | Azure Bot app registration credentials (CI: `E2E_TEAMS_APP_ID`, `E2E_TEAMS_APP_PASSWORD` secrets; `E2E_TEAMS_TENANT_ID` variable) |
| `E2E_TEAMS_DIRECTLINE_SECRET` | tests | Direct Line channel secret used to drive the bot (CI: secret) |

## Troubleshooting

- **Slack URL verification fails**: the ECS service may still be starting — re-run after
  `deploy.sh` reports the service stable. Check API Gateway/ECS logs in CloudWatch.
- **No Telegram reply**: run `set_telegram_webhook.py` again and inspect the printed
  `getWebhookInfo` — `last_error_message` shows delivery failures (e.g. secret mismatch).
- **Slack test times out but the bot replied in-channel (not in-thread)**: an unthreaded
  bot message is the handler's error path — check the agent/OpenAI key configuration.
