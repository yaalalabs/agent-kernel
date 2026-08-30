# Mathru - Maternal Health Companion

An Agent Kernel project that supports expectant mothers and the Public Health Midwife (PHM)
assigned to them over WhatsApp. See [SPEC.md](SPEC.md) for the full requirements.

The system is a triage-and-routing assistant, not a clinical decision system. It does not
diagnose, does not recommend medication, and does not originate clinical thresholds.

## Build Status

This is **phase 1** of the build order in `SPEC.md`: the WhatsApp channel with a single
passthrough agent, plus the project skeleton.

| Phase | Scope | State |
| --- | --- | --- |
| 1 | WhatsApp channel, `mathru_triage` passthrough agent, skeleton | Done |
| 2 | `intake_agent`, `schedule_agent`, schedule tools, SQLite persistence | Not started |
| 3 | `danger_sign_agent`, reference table, `escalate_to_phm`, guardrails, post-execution hook | Not started |
| 4 | `guidance_agent` and the knowledge base | Not started |

The phase 1 agent cannot register a mother, look up a visit date, screen a symptom, or reach a
PHM. It greets the sender, states what Mathru will do, and directs anyone reporting a symptom to
contact their PHM or nearest hospital directly.

## Prerequisites

- Python 3.12.
- [`uv`](https://github.com/astral-sh/uv) for dependency management.
- An OpenAI API key.
- A Meta Business account with a WhatsApp Business app and a verified or test phone number.
- A tunnel for local webhook delivery (ngrok or pinggy). There is no cloud deployment in this
  version.

## Project Layout

- `agent.py` defines the `mathru_triage` agent and exports `AGENTS`.
- `server.py` is the WhatsApp entry point, using `AgentWhatsAppRequestHandler` with
  `RESTAPI.run([handler])`.
- `demo.py` is the local Agent Kernel CLI entry point, for exercising the agent without WhatsApp.
- `tool.py` holds the Agent Kernel tools. Empty in phase 1.
- `config.yaml` configures the WhatsApp agent binding, sessions, and logging.
- `.env.example` is the template for the gitignored `.env` holding secrets.
- `SPEC.md` documents the requirements this project is built from.

## Setup

```bash
chmod +x build.sh
./build.sh
```

## Configure Environment Variables

Secrets are managed with a `.env` file, loaded by `python-dotenv`. Copy the template and fill it
in:

```bash
cp .env.example .env
```

```ini
OPENAI_API_KEY=sk-...
AK_WHATSAPP__VERIFY_TOKEN=your_secure_verify_token
AK_WHATSAPP__ACCESS_TOKEN=your_permanent_access_token
AK_WHATSAPP__PHONE_NUMBER_ID=123456789012345
AK_WHATSAPP__APP_SECRET=your_app_secret
```

`.env` is gitignored; `.env.example` holds placeholders only. Never commit real tokens or keys.
Exported shell variables still work and take precedence over `.env`, which is what you want in
CI or a container.

`AK_WHATSAPP__VERIFY_TOKEN` is a random string you invent; it must match what you enter in the
Meta developer portal. The agent name, acknowledgement message, and API version are set in
`config.yaml`, not the environment.

### Why `load_dotenv()` is called explicitly

Agent Kernel's `Config` already reads `.env` natively, but only for `AK_`-prefixed keys and only
into its own settings model, never into `os.environ`. The OpenAI Agents SDK reads
`OPENAI_API_KEY` straight from `os.environ`, so a key kept only in `.env` would not be found.
`server.py` and `demo.py` therefore call `load_dotenv()` before importing anything else, which
puts every key on `os.environ` and covers both consumers uniformly.

## Run Locally Without WhatsApp

```bash
uv run python demo.py
```

The default agent is `mathru_triage`. Inside the CLI you can also run `!list` and
`!select mathru_triage`.

## Run The WhatsApp Server

```bash
uv run server.py
```

The server listens on `http://localhost:8000`. Expose it with a tunnel:

```bash
ngrok http 8000
# or
ssh -p443 -R0:localhost:8000 a.pinggy.io
```

## Configure The WhatsApp Webhook

1. Go to <https://developers.facebook.com/apps> and select your app.
2. Open **WhatsApp > Configuration** and edit the webhook.
3. Set the callback URL to `https://<your-tunnel-host>/whatsapp/webhook`.
4. Set the verify token to the same value as `AK_WHATSAPP__VERIFY_TOKEN`.
5. Subscribe to the `messages` webhook field.

`AgentWhatsAppRequestHandler` answers the verification challenge on `GET /whatsapp/webhook`
automatically, so no extra code is needed to activate the URL.

## Verify The Round Trip

The local half of the chain is verified and working. With the server running:

```bash
curl http://127.0.0.1:8000/health
# {"status":"ok"}

curl "http://127.0.0.1:8000/whatsapp/webhook?hub.mode=subscribe&hub.verify_token=$AK_WHATSAPP__VERIFY_TOKEN&hub.challenge=1234567890"
# 1234567890
```

The challenge echo confirms the whole configuration path: `.env` to `Config.whatsapp.verify_token`
to the handler. A wrong verify token returns HTTP 403.

Phase 1 is complete when a live round trip works, which additionally needs real WhatsApp
credentials:

1. Start the server and the tunnel, and configure the webhook.
2. Send `Hello` from a WhatsApp number that is allowed to message your business or test number.
3. You receive the acknowledgement, then a greeting from the agent.
4. Server logs show the inbound webhook and the outbound reply.

During testing with a Meta test number, the sending number must be added to the app's allowed
recipient list first.

## Notes Carried Forward

- **PHM messaging window.** Escalation messages to a PHM (phase 3) can only be delivered to a
  number with an open 24-hour customer service window, or through a pre-approved message template.
  A PHM who has not messaged the business number recently cannot be reached with a freeform
  message.
- **Sessions.** The WhatsApp integration uses the sender's phone number as the session id, giving
  per-mother continuity. Mother records are persisted separately by tool-owned `sqlite3` storage
  in `tool.py` from phase 2; sqlite is not an Agent Kernel session backend, so `session.type`
  stays `in_memory`.
- **Danger-sign sources.** The reference table and its Ministry of Health and WHO source citations
  arrive in phase 3, along with the note that the table requires clinician review before any
  real-world use.
