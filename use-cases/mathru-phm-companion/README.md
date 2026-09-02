# Mathru - Maternal Health Companion

An Agent Kernel project that supports expectant mothers and the Public Health Midwife (PHM)
assigned to them over WhatsApp. See [SPEC.md](SPEC.md) for the full requirements.

The system is a triage-and-routing assistant, not a clinical decision system. It does not
diagnose, does not recommend medication, and does not originate clinical thresholds.

## Build Status

This is **phase 3** of the build order in `SPEC.md`: danger-sign screening, escalation, and the
PHM interface.

| Phase | Scope | State |
| --- | --- | --- |
| 1 | WhatsApp channel, `mathru_triage` passthrough agent, skeleton | Done |
| 2 | `intake_agent`, `schedule_agent`, schedule tools, SQLite persistence | Done |
| 3 | `danger_sign_agent`, reference table, escalation, role routing, guardrails, hook | Done |
| 4 | `guidance_agent` and the knowledge base | Not started |

Six agents. `mathru_triage` routes; `intake_agent` registers; `schedule_agent` answers visit
questions; `danger_sign_agent` screens symptoms; `phm_agent` serves midwives. `guidance_agent`
arrives in phase 4, and the system is coherent without it.

### The safety architecture

Severity is decided in Python, by keyword matching in `danger_signs.py`. The model passes the
mother's words through and receives a severity it cannot override or reinterpret. Every failure
mode leans toward escalation:

| Condition | Severity | Escalates |
| --- | --- | --- |
| exception anywhere during matching | `red` | yes |
| table `status: placeholder` | `red` | yes |
| matched a `red` entry | `red` | yes |
| matched an `amber` entry | `amber` | no |
| symptom reported, nothing matched | `amber` | no |
| no symptom reported at all | `green` | no |

`green` is a system-level state meaning nothing was reported. It is never a value in the table,
so a reported symptom can never resolve to green.

Escalation is **not a model decision**. `screen_danger_signs` calls `escalation.escalate()`
itself when the severity is red, in the same call. Nothing in `escalation.py` is bound as a tool.

Delivery can fail: a PHM whose 24-hour WhatsApp window has closed cannot be reached. When that
happens the escalation is still persisted, as `undelivered`, it is logged, it appears at the top
of that PHM's caseload, and the mother is told in the same turn to contact her PHM or nearest
hospital **herself**. No path implies help is on the way when it is not.

### The clinical data is not populated yet

`data/antenatal_schedule.yaml`, `data/immunization_schedule.yaml`, and `data/danger_signs.yaml`
ship with **placeholder values only**, each marked `# TODO`. They are structurally correct but
clinically meaningless, and all three carry `status: placeholder`.

The tools relay that marker to the agent as `data_status: placeholder`, and `schedule_agent` is
instructed that when it sees it, it must **refuse to read out any dates** and tell the mother the
schedule is not available yet and that her PHM can tell her when her next visit is due.

Each file carries a `provenance:` block, and `provenance_test.py` makes it load-bearing: a file
cannot claim `status: sourced` until it names its document, that document's printed date, a
`.gov.lk` or `who.int` URL, and a second cross-check. Citing a Scribd re-upload fails the suite.
Only the exact string `sourced` is trusted, so a typo fails toward escalation rather than away
from it.

The danger-sign table guards the same way, but in the opposite direction. A schedule it cannot
trust, it declines to read out. A symptom it cannot screen, it escalates. **While
`data/danger_signs.yaml` is a placeholder, every reported symptom is treated as `red` and
escalated to the assigned PHM.** An unpopulated table cannot rule anything out, so it is never
allowed to reassure.

So the system runs end to end, but it will not produce real appointment dates or real severities
until the Ministry of Health values are sourced and the three data files are filled in. Every
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
- `danger_signs.py` decides severity by keyword matching. No model involvement.
- `escalation.py` delivers and persists escalations. Not model-callable.
- `hooks.py` is the post-execution hook blocking unsafe outbound language.
- `redaction.py` redacts phone numbers from log output only.
- `data/*.yaml` hold the visit schedules, the danger-sign table, and the hook's block list.
- `provenance.py` enforces that a clinical file cannot claim `sourced` without a citation.
- `guardrails/` holds the guardrail configs and the reasoning behind them.
- `SOURCING.md` records verified sources, dead ends, and the stale-document traps found.
- `*_test.py` are the unit tests.
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

To exercise the PHM side, seed a mother first, then run as the number that seeding assigned as
her PHM. `resolve_role` will resolve that sender to `phm` and triage routes to `phm_agent`:

```bash
uv run demo.py --seed                     # registers a mother, prints her PHM's number
uv run demo.py --session-id 94112223344   # now you are the midwife
```

Escalation delivery needs real WhatsApp credentials. Without them the send fails, which exercises
the undelivered path: the escalation is persisted, it shows up in the caseload, and the mother is
told to seek care herself.

## Running The Tests

```bash
uv run pytest
```

Every safety rule in the architecture above has a test. The suite covers the date arithmetic and
validation rules; the storage behaviours most likely to break; each row of the severity table
including a forced exception and the placeholder guard; escalation on both delivery success and
delivery failure, asserting the failure text never implies help is coming; the hook in **both**
directions, blocking diagnosis and medication language while letting escalation messages and
danger-sign action strings through untouched; log redaction *and* its scope, proving the
escalation path still receives the real unredacted number; and the case of a PHM who is herself
pregnant keeping her own danger-sign path open.

Every date test injects `today`, so none of them depend on the day they are run.

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
- **The verbatim excerpt is deliberate.** The escalation sent to a PHM contains a short, unedited
  excerpt of the mother's own words, capped at 300 characters. A midwife triaging a report needs
  how the mother actually described it, not a model's paraphrase of it. This does mean her raw
  phrasing leaves the system, to one specific recipient: her assigned PHM.
- **Moderation categories are narrow on purpose.** `self-harm` and `violence/graphic` are
  excluded from the input guardrail. A mother describing heavy bleeding or a baby that has
  stopped moving must never be blocked before `screen_danger_signs` runs. The trade-off is a
  smaller moderation net; see `guardrails/README.md`.
- **The block list is not exhaustive.** `hooks.py` matches a hand-written list in
  `data/blocked_language.yaml`. Broad terms like `mg`, `ml`, and `dose` will produce false
  positives, which is why every block is logged with the original reply, redacted, so the rate
  is measurable.
- **Escalation acknowledgement is PHM-side only.** Acknowledging closes the escalation on the
  midwife's caseload and sends nothing to the mother.
- **The visit schedules and the danger-sign table are placeholders.** See the build status above.
  No real appointment date and no real severity can be produced until the Ministry of Health
  values are sourced.
- **No clinician review.** Nothing in this repository has been reviewed by a clinician, and the
  data files say so in their headers.

## Notes Carried Forward

- **PHM messaging window.** Escalation messages can only be delivered to a number with an open
  24-hour customer service window, or through a pre-approved message template. A PHM who has not
  messaged the business number recently **cannot be reached** with a freeform message. This is
  not hypothetical: it is the expected failure mode in production, which is why undelivered
  escalations are persisted, surfaced first in the caseload, and disclosed to the mother in the
  same turn. Approved templates are the production fix and are not implemented here.
- **Sessions.** The WhatsApp integration uses the sender's phone number as the session id, giving
  per-mother continuity. Mother records are persisted separately by tool-owned `sqlite3` storage
  in `tool.py` from phase 2; sqlite is not an Agent Kernel session backend, so `session.type`
  stays `in_memory`.
- **Clinical sources.** Each file in `data/` carries a `provenance:` block naming the document
  its values came from. All three are still `placeholder`, so every block reads `TODO`.
  [SOURCING.md](SOURCING.md) records what has been verified so far, including a live trap: the
  current Epidemiology Unit site serves a **2017** immunisation schedule as its top result, with
  2023 file metadata that masks its age. Citations belong here once values land:

  | File | Source | Citation |
  | --- | --- | --- |
  | `antenatal_schedule.yaml` | Family Health Bureau | _TODO: Maternal Care Package_ |
  | `immunization_schedule.yaml` | Epidemiology Unit | _TODO: current EPI schedule, cross-checked against CHDR_ |
  | `danger_signs.yaml` | FHB, supplemented by WHO | _TODO_ |
