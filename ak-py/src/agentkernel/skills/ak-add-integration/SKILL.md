---
name: ak-add-integration
description: >
  Add a messaging platform integration to an existing Agent Kernel project.
  This skill guides you through adding Slack, WhatsApp, Messenger, Instagram,
  Telegram, or Gmail integration by generating configuration, updating dependencies,
  and setting up webhook handlers. Designed for users extending their agents.
license: Apache-2.0
metadata:
  author: yaalalabs
  category: user
---

# Add a Messaging Integration

Use this skill to add a messaging platform integration to your Agent Kernel project.

## Instructions for the Agent

When the user wants to add a messaging integration, follow this workflow:

### Step 1: Identify the Project

Check the user's current project for:
- An existing `pyproject.toml` with `agentkernel` dependency
- An agent definition file (e.g., `app.py`, `server.py`, `demo.py`)
- An existing `config.yaml`

If not found, suggest using the `ak-init` skill first.

### Step 2: Ask Which Integration

Which messaging platform would you like to integrate?

1. **Slack** — Bot that responds in Slack channels and threads
2. **WhatsApp** — Bot via WhatsApp Business API (Meta)
3. **Facebook Messenger** — Bot via Messenger Platform (Meta)
4. **Instagram** — Bot via Instagram Messaging API (Meta)
5. **Telegram** — Bot via Telegram Bot API
6. **Gmail** — Email-based agent via Gmail API (polling)

### Step 3: Generate Changes

#### For Slack

**1. Update pyproject.toml dependencies:**

Add `slack` to the extras:
```toml
dependencies = [
    "agentkernel[openai,api,slack]>=0.2.13",
]
```

**2. Update config.yaml:**

```yaml
slack:
  agent_acknowledgement: "I'm processing your request"
  # agent: general  # Optional: specify which agent handles Slack messages
```

**3. Update the server file:**

```python
from agentkernel.api import RESTAPI
from agentkernel.slack import AgentSlackRequestHandler
# ... existing agent imports and definitions ...

if __name__ == "__main__":
    RESTAPI.run([AgentSlackRequestHandler()])
```

**4. Environment variables needed:**

```bash
export SLACK_BOT_TOKEN="xoxb-..."          # Bot User OAuth Token
export SLACK_SIGNING_SECRET="..."          # App signing secret
```

**5. Setup instructions:**
- Create a Slack App at https://api.slack.com/apps
- Enable **Event Subscriptions** → set Request URL to `https://<your-domain>/slack/events`
- Subscribe to bot events: `message.channels`, `message.groups`, `message.im`, `message.mpim`
- Install the app to your workspace
- Copy Bot Token and Signing Secret to environment variables

---

#### For WhatsApp

**1. Update pyproject.toml:**

```toml
dependencies = [
    "agentkernel[openai,api,whatsapp]>=0.2.13",
]
```

**2. Update config.yaml:**

```yaml
whatsapp:
  verify_token: "your-verify-token"
  # agent: general
  # access_token and phone_number_id set via env vars
```

**3. Update the server file:**

```python
from agentkernel.api import RESTAPI
from agentkernel.whatsapp import AgentWhatsAppRequestHandler
# ... existing agent imports and definitions ...

if __name__ == "__main__":
    RESTAPI.run([AgentWhatsAppRequestHandler()])
```

**4. Environment variables:**

```bash
export AK_WHATSAPP__ACCESS_TOKEN="..."         # WhatsApp Business API access token
export AK_WHATSAPP__PHONE_NUMBER_ID="..."      # Phone number ID from Meta
export AK_WHATSAPP__APP_SECRET="..."           # App secret for signature verification
```

**5. Setup instructions:**
- Create a Meta App at https://developers.facebook.com
- Set up WhatsApp Business API
- Configure webhook URL: `https://<your-domain>/whatsapp/webhook`
- Set verify token to match your `config.yaml`

---

#### For Facebook Messenger

**1. Update pyproject.toml:**

```toml
dependencies = [
    "agentkernel[openai,api,messenger]>=0.2.13",
]
```

**2. Update config.yaml:**

```yaml
messenger:
  verify_token: "your-verify-token"
  # agent: general
```

**3. Update the server file:**

```python
from agentkernel.api import RESTAPI
from agentkernel.messenger import AgentMessengerRequestHandler
# ... existing agent imports and definitions ...

if __name__ == "__main__":
    RESTAPI.run([AgentMessengerRequestHandler()])
```

**4. Environment variables:**

```bash
export AK_MESSENGER__ACCESS_TOKEN="..."
export AK_MESSENGER__APP_SECRET="..."
```

**5. Setup instructions:**
- Create a Meta App and add Messenger product
- Configure webhook: `https://<your-domain>/messenger/webhook`
- Subscribe to `messages` events

---

#### For Instagram

**1. Update pyproject.toml:**

```toml
dependencies = [
    "agentkernel[openai,api,instagram]>=0.2.13",
]
```

**2. Update config.yaml:**

```yaml
instagram:
  verify_token: "your-verify-token"
  # agent: general
```

**3. Update the server file:**

```python
from agentkernel.api import RESTAPI
from agentkernel.instagram import AgentInstagramRequestHandler

if __name__ == "__main__":
    RESTAPI.run([AgentInstagramRequestHandler()])
```

**4. Environment variables:**

```bash
export AK_INSTAGRAM__ACCESS_TOKEN="..."
export AK_INSTAGRAM__INSTAGRAM_ACCOUNT_ID="..."
```

---

#### For Telegram

**1. Update pyproject.toml:**

```toml
dependencies = [
    "agentkernel[openai,api,telegram]>=0.2.13",
]
```

**2. Update config.yaml:**

```yaml
telegram:
  # agent: general
  # bot_token set via env var
```

**3. Update the server file:**

```python
from agentkernel.api import RESTAPI
from agentkernel.telegram import AgentTelegramRequestHandler

if __name__ == "__main__":
    RESTAPI.run([AgentTelegramRequestHandler()])
```

**4. Environment variables:**

```bash
export AK_TELEGRAM__BOT_TOKEN="..."            # From @BotFather
export AK_TELEGRAM__WEBHOOK_SECRET="..."       # Your webhook secret
```

**5. Setup instructions:**
- Create a bot via Telegram @BotFather
- Set webhook: `https://api.telegram.org/bot<token>/setWebhook?url=https://<your-domain>/telegram/webhook`

---

#### For Gmail

**1. Update pyproject.toml:**

```toml
dependencies = [
    "agentkernel[openai,api,gmail]>=0.2.13",
]
```

**2. Update config.yaml:**

```yaml
gmail:
  poll_interval: 30        # seconds between email checks
  label_filter: "INBOX"    # Gmail label to monitor
  token_file: "token.json" # OAuth token file path
  # agent: general
```

**3. Update the server file:**

```python
from agentkernel.api import RESTAPI
from agentkernel.gmail import AgentGmailRequestHandler

if __name__ == "__main__":
    RESTAPI.run([AgentGmailRequestHandler()])
```

**4. Setup instructions:**
- Create a Google Cloud project
- Enable Gmail API
- Create OAuth 2.0 credentials
- Download `credentials.json` and run the OAuth flow to generate `token.json`

---

### Step 4: Multiple Integrations

Multiple integrations can run simultaneously:

```python
from agentkernel.api import RESTAPI
from agentkernel.slack import AgentSlackRequestHandler
from agentkernel.whatsapp import AgentWhatsAppRequestHandler
from agentkernel.telegram import AgentTelegramRequestHandler

if __name__ == "__main__":
    RESTAPI.run([
        AgentSlackRequestHandler(),
        AgentWhatsAppRequestHandler(),
        AgentTelegramRequestHandler(),
    ])
```

Update `pyproject.toml`:
```toml
dependencies = [
    "agentkernel[openai,api,slack,whatsapp,telegram]>=0.2.13",
]
```

### Step 5: Verify

After making changes:
1. Run `uv sync` to install new dependencies
2. Set environment variables for the integration
3. Start the server: `python server.py`
4. Check health: `curl http://localhost:8000/health`
5. Configure the platform webhook to point to your server URL

---

### What to Do Next

Your messaging integration is connected. Here's what you might do next:

- **Add more tools & agents** → Use the `ak-build` skill to add new tools and agents that handle platform-specific interactions.
- **Add guardrails** → Use the `ak-add-capabilities` skill to add input/output guardrails — especially important for public-facing messaging channels.
- **Deploy to cloud** → Use the `ak-cloud-deploy` skill to deploy your agent to AWS or Azure so your webhook endpoints are publicly accessible.
- **Set up testing** → Use the `ak-test` skill to test your agent's responses before going live.
