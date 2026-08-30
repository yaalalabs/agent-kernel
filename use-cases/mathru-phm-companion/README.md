# Mathru - Maternal Health Companion

An Agent Kernel project that supports expectant mothers and the Public Health Midwife (PHM)
assigned to them over WhatsApp. See [SPEC.md](SPEC.md) for the full requirements.

The system is a triage-and-routing assistant, not a clinical decision system. It does not
diagnose, does not recommend medication, and does not originate clinical thresholds.

## Build Status

This is **phase 2** of the build order in `SPEC.md`: registration and the visit schedules.

| Phase | Scope | State |
| --- | --- | --- |
| 1 | WhatsApp channel, `mathru_triage` passthrough agent, skeleton | Done |
| 2 | `intake_agent`, `schedule_agent`, schedule tools, SQLite persistence | Done |
| 3 | `danger_sign_agent`, reference table, `escalate_to_phm`, guardrails, post-execution hook | Not started |
| 4 | `guidance_agent` and the knowledge base | Not started |

A mother can now register over WhatsApp and ask when her next visit is due. `mathru_triage` is a
router that hands off to `intake_agent` or `schedule_agent` and answers nothing itself.

The system still cannot screen a symptom or reach a PHM. Anyone reporting a symptom is told that
screening is not available yet and directed to contact their PHM or nearest hospital.

### The schedule data is not populated yet

`data/antenatal_schedule.yaml` and `data/immunization_schedule.yaml` ship with **placeholder
values only**, each marked `# TODO`. They are structurally correct but clinically meaningless,
and both carry `status: placeholder`.

The tools relay that marker to the agent as `data_status: placeholder`, and `schedule_agent` is
instructed that when it sees it, it must **refuse to read out any dates** and tell the mother the
schedule is not available yet and that her PHM can tell her when her next visit is due.

So phase 2 runs end to end, but it will not produce real appointment dates until the Ministry of
Health values are sourced and the two data files are filled in. That is deliberate: an agent that
knows its own data is untrustworthy and declines is the correct behaviour for this domain. Every
clinical constant lives in those files, including `term_gestational_weeks`, so no clinical value
is hardcoded anywhere in the Python.

## Prerequisites

- Python 3.12.
- [`uv`](https://github.com/astral-sh/uv) for dependency management.
- An OpenAI API key.
- A Meta Business account with a WhatsApp Business app and a verified or test phone number.
- A tunnel for local webhook delivery (ngrok or pinggy). There is no cloud deployment in this
  version.

## Project Layout

- `agent.py` defines `mathru_triage`, `intake_agent`, and `schedule_agent`, and exports `AGENTS`.
- `server.py` is the WhatsApp entry point, using `AgentWhatsAppRequestHandler` with
  `RESTAPI.run([handler])`.
- `demo.py` is the local entry point, for exercising the agent graph without WhatsApp.
- `tool.py` holds the Agent Kernel tools, bound with `OpenAIToolBuilder.bind`.
- `store.py` is the tool-owned SQLite storage, with the schema in one place.
- `schedules.py` is the pure date arithmetic and input validation. No model involvement.
- `data/*.yaml` hold the visit schedules. Placeholder values only; see above.
- `schedules_test.py` and `store_test.py` are the unit tests.
- `config.yaml` configures the WhatsApp agent binding, sessions, and logging.
- `.env.example` is the template for the gitignored `.env` holding secrets.
- `SPEC.md` documents the requirements this project is built from.

### Identity is never a tool parameter

No tool accepts the mother's phone number. Each one resolves her from
`ToolContext.get().session.id`, which the WhatsApp integration sets to the sender's number. This
means the model cannot assert who is speaking, and a mother never has to restate details she has
already given.

The one phone number that *is* a parameter is `phm_phone`, since it is a data field the mother
supplies and cannot be derived from the session.

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

One optional non-secret setting: `MATHRU_DB_PATH` sets where the SQLite database lives,
defaulting to `./mathru.db`. The database is gitignored via `*.db`.

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

Because every tool resolves the mother from the session id, the demo needs to impersonate a
specific WhatsApp sender. Agent Kernel's built-in `CLI.main()` generates a fresh `uuid4` session
id per run and takes no arguments, so `demo.py` drives `AgentService` directly instead and passes
a session id to its public `select()` method.

```bash
uv run demo.py                      # sender 94771234567, unregistered -> exercises intake
uv run demo.py --seed               # pre-registers a sample mother and PHM -> exercises schedules
uv run demo.py --session-id 9477... # impersonate any number
```

`--seed` derives its EDD from today, so the seeded record never goes stale. Inside the REPL,
`!clear` resets the conversation while leaving the registration record intact, and `!quit` exits.

## Running The Tests

```bash
uv run pytest
```

The suite covers the date arithmetic and validation rules in `schedules.py`, plus the two storage
behaviours most likely to break: that re-registering the same sender updates their fields while
preserving `created_at`, and that the `CHECK` constraint rejects both-null and both-populated
dates. Every date test injects `today`, so none of them depend on the day they are run.

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

## Known Limitations

- **The PHM assignment is free-text, and that is a prototype limitation.** A mother types her
  assigned PHM's phone number during registration, and in phase 3 that number decides where her
  symptom report is escalated. A typo would send her health information to a stranger. The tool
  validates the format and rejects the most likely error, a mother entering her own number, but
  neither check can confirm the number belongs to her actual PHM. In production the assignment
  would be resolved from the MOH division registry using her MOH area, not accepted from user
  input.
- **The visit schedules are placeholders.** See the build status above. No real appointment date
  can be produced until the Ministry of Health values are sourced.
- **No clinician review.** Nothing in this repository has been reviewed by a clinician, and the
  data files say so in their headers.

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
