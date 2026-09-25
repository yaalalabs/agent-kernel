# Mathru — Maternal Health Companion

A WhatsApp agent built on Agent Kernel that supports expectant mothers and the Public
Health Midwife (PHM) assigned to them. Mothers register, ask about their upcoming clinic
visits, and report symptoms in plain language. The screening tool classifies reported text
in Python and attempts to notify an approved assigned midwife when severity is red.

Addresses **UN SDG 3 — Good Health and Well-being**, targets 3.1 (maternal mortality) and
3.2 (newborn and under-five mortality).

> **This is a competition prototype, not a clinical tool.** It has not been reviewed by a
> clinician and must not be used to make care decisions. Every clinical data file currently
> ships as `placeholder`: schedule tools withhold dates, and every nonempty symptom passed
> to screening receives a red classification. See [Data provenance](#4-data-provenance) and
> [Known limitations](#7-known-limitations).

---

## 1. Problem statement

Mathru explores how mothers can ask about clinic schedules and report concerns between
visits, and how those reports can reach an assigned Public Health Midwife with context.
It uses WhatsApp for both sides of that exchange, alongside existing clinic records and
care channels. The competition prototype has not measured clinical outcomes or service
adoption and does not replace professional care.

## 2. Solution overview

Mathru puts a multi-agent system on WhatsApp serving both sides of that relationship.

**For mothers:** register with MOH division, expected delivery date or child date of
birth, and assigned PHM. Ask when the next clinic visit is due. Report symptoms in
ordinary language.

**For midwives:** receive escalations with the mother's context attached, query the
current caseload, and acknowledge escalations to close them out.

### Agents

| Agent | Role |
|---|---|
| `mathru_triage` | Entry point. Routes by intent and by resolved role. Holds only `resolve_role`. |
| `intake_agent` | Registration. Confirms fields back before saving. |
| `schedule_agent` | Antenatal, immunisation, and child health schedule queries. |
| `danger_sign_agent` | Structured symptom screening and escalation. |
| `phm_agent` | Caseload queries and escalation acknowledgement. |

### How it uses Agent Kernel

- **WhatsApp integration** as the sole user interface, via
  `WhatsAppInboundAdapter`, `WebhookRESTRequestHandler`, and `IOHandler`.
  The default in-memory execution pipeline runs in the same local process.
- **Multi-agent handoffs** through the OpenAI Agents module, with `OpenAIModule`
  registering every handoff target.
- **Session memory** keyed on the sender's phone number. The WhatsApp adapter sets
  `Session.id` from the sender, so per-mother conversation continuity comes from the
  framework rather than a parallel mechanism.
- **`ToolContext`** for identity resolution inside every tool.
- **Guardrails** for input moderation/jailbreak and output NSFW Text checks (see
  `guardrails/README.md`). The input guardrail is a custom subclass that **fails open** when
  the guardrail service is unreachable; see section 3.
- **Post-execution hooks** checking final agent replies for diagnosis and medication
  language. Registered on the entry agent so it also sees replies produced
  after a handoff; direct PHM escalation messages use a separate delivery path.

## 3. Safety design

The intended boundary is that the model handles conversation and routing while Python
computes dates, classifies symptom text, and attempts escalation. Routing and tool calls
still depend on the model, so this is not a guarantee that every symptom reaches screening.

**Severity is decided in code once screening runs.** `screen_danger_signs` returns the
severity and action from the reference table or a fallback; the model is instructed to
relay them unchanged. The matching behavior is:

| Condition | Severity | Automatic escalation attempt |
|---|---|---|
| no symptom text | `green` | no |
| exception during matching | `red` | yes |
| reference table not exactly `sourced` | `red` | yes |
| matched a `red` entry | `red` | yes |
| matched only `amber` entries | `amber` | no |
| symptom text, no match in a sourced table | `amber` | no |

An unmatched symptom receives instructions to contact the PHM; it does not automatically
send a report. While the shipped table is a placeholder, every nonempty symptom passed
to screening instead receives `red`. `green` is reserved for empty symptom text.

**Red escalation is internal to the screening tool.** It does not require a second model
call. A registered mother must have an operator-approved PHM assignment for delivery.
For an unregistered sender, the tool returns instructions to seek care directly without
creating an escalation row. For registered senders, failed or unapproved delivery is
recorded as `undelivered`, and the tool instructs the model to relay the direct-care fallback.
SQLite failures are not handled as delivery failures and can still interrupt this path.

**Identity comes from the channel.** The server requires the WhatsApp app secret for
webhook signature verification. Tools derive the caller from `ToolContext.get().session.id`.
An operator-managed registry approves PHM numbers and MOH areas independently of mother
registration. Caseload access and acknowledgements are limited to approved areas and
current assignments. A PHM who is also registered as a mother retains her own symptom path.

**Outbound agent replies are filtered.** The entry agent's post-hook checks final text,
including replies produced after handoff, against diagnosis and medication block lists.
Known action strings are excluded from scanning, but unsafe text elsewhere in the reply
can still cause replacement of the whole reply. This is a phrase filter, not clinical
validation. The separately constructed PHM escalation is sent directly through the outbound
adapter and does not pass through this hook.

**Guardrail failures have explicit behavior.** Input moderation and jailbreak tripwires
still block a turn. `ResilientInputGuardrail` logs other validation exceptions and lets the
turn continue; an uninitialized guardrail client also passes through. This keeps an input
validation failure from automatically halting screening, but does not recover an unavailable
agent model. The built-in output guardrail can replace a reply on a tripwire and passes it
through on validation errors. See [guardrail configuration](guardrails/README.md).

**Stored identity and display data are separated.** SQLite retains phone numbers for
routing. PHM tool results omit routing identifiers and raw delivery errors. The mother's
profile and registration results still contain her own record, and a free-text symptom
excerpt may contain identifiers supplied by the sender. Log-record creation applies phone
redaction before handlers run, including non-propagating Agent Kernel loggers; it never
changes stored records or delivery destinations. This is phone-pattern redaction, not
complete PII removal.

## 4. Data provenance

Clinical reference data lives in `data/`, never in code and never in a prompt. Each file
carries a `provenance:` block, and its `status` propagates through the tools into what the
mother is told. `provenance_test.py` makes that header load-bearing: a file cannot claim
`sourced` until it names its document, that document's **printed** date, a `.gov.lk` or
`who.int` URL, and a second cross-check. Citing a re-upload fails the test suite. Only the
exact string `sourced` is trusted, so a typo fails toward escalation rather than away from it.

| File | Status | Notes |
|---|---|---|
| `data/immunization_schedule.yaml` | `placeholder` | Values captured. National Immunization Schedule poster, Epidemiology Unit, **© 2017 printed on its face**, [epid.gov.lk](https://www.epid.gov.lk/storage/post/pdfs/en_6403b42a75fa4_Doc2.pdf), retrieved 2026-09-02. Agrees line for line with the Essential Health Services Package 2019. Both predate the 2022 CHDR circular, which mandates the CHDR but does not reproduce the schedule. |
| `data/developmental_screening.yaml` | `placeholder` | Ten screening points, 2–60 months. Relayed from a Ministry of Health performance report describing the tool, not from the schedule document itself. |
| `data/vitamin_a.yaml` | `placeholder` | **Two sources disagree**: the national strategy says every 6 months from 6 to 60 months (10 doses); reported service data shows 6, 18 and 36 (3 doses). The file encodes the strategy reading and records the conflict. |
| `data/mmn_supplementation.yaml` | `placeholder` | Three 60-day periods, not appointments. Term / normal-birth-weight pathway only; the system stores nothing that could identify a child it does not apply to, so the file carries a caveat that travels with the data. |
| `data/antenatal_schedule.yaml` | `placeholder` | **Empty.** The FHB Maternal Care Package was not locatable through the resource library's unit, type, or search filters. `term_gestational_weeks` is blocked on the same document. |
| `data/danger_signs.yaml` | `placeholder` | **Empty.** While it stays a placeholder, every nonempty symptom passed to screening is `red`. |
| `data/blocked_language.yaml` | populated | Not clinical guidance — a list of things the system must never say. A placeholder block list would block everything or nothing, neither of which fails safe. |

When a file's status is anything other than `sourced`, the agent names which parts of the
calendar it cannot speak for rather than quietly omitting them. **No clinical value in this
repository has been reviewed by a clinician.**

`SOURCING.md` records what was verified, the dead ends, and the traps — including that the
Epidemiology Unit's current site serves that 2017 poster as its top result with 2023 file
metadata that masks its age.

## 5. Setup instructions

### Prerequisites

- Python 3.12 (the version in `.python-version`) and [`uv`](https://docs.astral.sh/uv/).
- An OpenAI API key with access to the configured models for interactive runs.
- For WhatsApp: a Meta app, WhatsApp Business Account, business phone number, webhook
  credentials including the app secret, a tunnel, and a participating PHM's second number.
- For registration and PHM operations: the operator-managed registry described below.

Unit tests mock external services and do not need live API credentials. The CLI can start
without WhatsApp credentials; any real escalation attempt then follows the undelivered path.

### Install

Run all following commands from this directory so `config.yaml`, guardrail JSON paths,
and the default database path resolve consistently:

```bash
cd use-cases/mathru-phm-companion
uv sync --frozen --all-extras --dev
```

The same `uv` command works in PowerShell. On Bash, `./build.sh` runs it for you. The lockfile
resolves Agent Kernel **0.9.3**, using the published WhatsApp adapter and pipeline APIs;
this project does not import the repository's `ak-py/src` checkout. The dependency range is
`>=0.9.3,<0.10`; deliberate upgrades must refresh and retest `uv.lock`.

### Environment

Secrets are loaded from a `.env` file via `python-dotenv`; `cp .env.example .env` and fill
it in. In PowerShell use `Copy-Item .env.example .env`. Existing process environment
variables take precedence. The examples below use Bash syntax; putting the values in `.env`
works in either shell.

```bash
export OPENAI_API_KEY="sk-..."
export AK_WHATSAPP__VERIFY_TOKEN="a_string_you_choose"
export AK_WHATSAPP__ACCESS_TOKEN="meta_system_user_token"
export AK_WHATSAPP__APP_SECRET="meta_app_secret"
export AK_WHATSAPP__PHONE_NUMBER_ID="meta_phone_number_id"
export MATHRU_DB_PATH="./mathru.db"     # optional
```

The app secret is required by `server.py` to authenticate webhook sender identities.
Use an access token suitable for your Meta app configuration and check its expiry before
the demonstration; a temporary setup token is not a durable deployment credential.

### PHM approvals

Copy `phm_registry.example.yaml` to `phm_registry.yaml` (gitignored). The service operator
must independently verify each PHM's number and MOH division before adding an entry:

```yaml
phms:
  - phone: "94112223344"
    moh_areas: [Colombo]
```

The number above is the local CLI demo identity. For WhatsApp, use the independently
verified number of your participating PHM. Set `MATHRU_PHM_REGISTRY` for a different file
location. Restrict write access to the operator; agent tools never edit this file.

An absent, empty, or malformed registry grants no PHM privileges. Mother registration
checks both number and MOH area. Caseload access, acknowledgements, and escalation delivery
also check approvals; removing an entry takes effect on subsequent checks without restart.
Existing assignments do not grant access on their own. Reports to an unapproved assignment
are persisted as undelivered and the mother is directed to seek care herself.

For `demo.py --seed`, explicitly add the sample approval above first. The CLI's
`--session-id` impersonation is a local developer tool; do not expose it as a public API.

### Model and rate limits

All five agents explicitly select a model. `MATHRU_MODEL` overrides **the agents only**:

```bash
export MATHRU_MODEL="gpt-5.4-mini"      # optional; agent default
```

Guardrail model settings are independent. The checked-in chat-model settings all default
to `gpt-5.4-mini`, but changing `MATHRU_MODEL` does not update any of these:

| Setting | How to override |
|---|---|
| Input guardrail wrapper model | `AK_GUARDRAIL__INPUT__MODEL`, or `guardrail.input.model` in `config.yaml` |
| Output guardrail wrapper model | `AK_GUARDRAIL__OUTPUT__MODEL`, or `guardrail.output.model` in `config.yaml` |
| Jailbreak check model | Edit `input.guardrails[].config.model` for `Jailbreak` in `guardrails/input.json` |
| NSFW Text check model | Edit `output.guardrails[].config.model` for `NSFW Text` in `guardrails/output.json` |

To use one chat model throughout, set both `AK_GUARDRAIL__*__MODEL` variables to the same
value as `MATHRU_MODEL` and edit both JSON check models. JSON values are literal; environment
variable placeholders are not expanded there. The Moderation check uses its own moderation
service rather than the agent chat model.

Request and token limits depend on the account, project, and model; check your account's
limits rather than assuming a universal daily quota. See the
[OpenAI rate-limit guide](https://developers.openai.com/api/docs/guides/rate-limits).

One user turn can make multiple model requests for routing, handoffs, and tools. Input and
output guardrail wrappers add chat-completion calls, and their configured checks can make
additional requests. Retries add more. There is no fixed requests-per-turn count or
threefold cost multiplier; measure the actual walkthrough with your account.

Keep guardrails enabled for the normal demonstration. To isolate a local debugging run,
you can temporarily set `AK_GUARDRAIL__INPUT__ENABLED=false` and
`AK_GUARDRAIL__OUTPUT__ENABLED=false` in the process environment or `.env`, then restore
both to `true`. A run with these disabled does not validate guardrail behavior.

`load_dotenv()` is called explicitly because Agent Kernel's own `.env` support reads only
`AK_`-prefixed keys into its settings model, never into `os.environ` — and the OpenAI SDK
reads `OPENAI_API_KEY` from `os.environ` directly.

### Webhook

1. Start the server and the tunnel (see below).
2. In the Meta app dashboard, set the callback URL to
   `https://<your-tunnel>/whatsapp/webhook`.
3. Set the verify token to the value of `AK_WHATSAPP__VERIFY_TOKEN`.
4. Subscribe to the `messages` field.

## 6. How to run the solution

### Local CLI — no WhatsApp required

```bash
uv run --frozen demo.py                         # existing or unregistered demo sender
uv run --frozen demo.py --seed                  # seed mother after approving the sample PHM
uv run --frozen demo.py --session-id 94112223344 # act as the approved sample PHM
```

`demo.py` drives `AgentService` directly rather than `CLI.main()`, because the built-in CLI
generates a fresh uuid4 session id per run and every tool resolves identity from the session.
The CLI still uses the live model, and configured WhatsApp credentials allow real outbound
escalation. Use a separate `MATHRU_DB_PATH` and registry for demo identities; `--seed` updates
the selected mother record, so omit it when reopening an existing session.

### WhatsApp

```bash
uv run --frozen python server.py             # terminal 1
ngrok http 8000                     # terminal 2
```

Then message your business number.

### End-to-end walkthrough

1. Have the operator approve the participating PHM number and MOH area. Start the server
   and tunnel, then complete the webhook subscription above.
2. From the PHM's phone, message the business number to open the messaging window.
3. From the mother's phone, complete registration and confirm the details. Ask when the
   next clinic visit is due; expect the placeholder response, not dates.
4. Report a symptom. Screening attempts escalation to the approved PHM in the same tool call.
5. From the PHM's phone, query the caseload and acknowledge the escalation. Repeating that
   acknowledgement reports that no open escalation with that ID belongs to the caller.

To exercise an immediate delivery rejection, use a verified test recipient for which the
Cloud API rejects the send. The unit tests cover this deterministically with a mocked
adapter error. A closed messaging window can also cause a later asynchronous failure:
this prototype does not consume delivery-status updates, so API acceptance alone does not
prove the recipient received or read the message.

At step 3, expect the agent to say it cannot give dates yet and to name which parts of the
calendar are unavailable. That is the placeholder guard working, not a bug.

### Tests and local checks

```bash
uv run --frozen pytest -q
uv run --frozen black --check .
uv run --frozen isort --check-only --skip .venv --skip .pytest_cache .
uv lock --check
uv pip check
```

The suite covers date arithmetic, provenance, registry authorization and revocation,
SQLite integrity, escalation outcomes, reply filtering, logging redaction, and server
startup wiring. It uses temporary databases and registries and mocks external delivery;
it does not demonstrate a live WhatsApp-to-model round trip or clinical correctness.

Formatting follows this use case's `pyproject.toml`: Black and isort with a 120-character
line length. The repository's `make lint-check-all` covers core and selected examples;
it does not include `use-cases/`, so run the checks above explicitly.

## 7. Known limitations

- **Clinical data is unverified.** All six reference files remain `placeholder`.
  Antenatal and danger-sign tables are empty; captured child-health values are gated.
  Vitamin A sources disagree, and the MMN schedule covers only a limited pathway.
- **Routing and final wording depend on the model.** Python determines severity only
  after the model calls screening. Prompt instructions and phrase filters are not a
  guarantee against missed screening, altered advice, or unsafe output in every language.
- **PHM verification is operator-managed.** The registry validates numbers and MOH areas,
  not each individual mother-to-PHM relationship within an area. It is not connected to
  an official registry. The local CLI can impersonate a session and must remain private.
- **API acceptance is not delivery confirmation.** `delivered` means the outbound adapter
  returned successfully. Delivery-status webhooks and read receipts are not tracked;
  later rejection is not reflected in the stored status. No WhatsApp templates are implemented.
- **Persistence and delivery are not transactional.** A database failure can interrupt
  escalation handling, including after a send. There is no durable retry or recovery worker.
- **Excerpts can contain sensitive text.** PHM alerts include the sender's bounded words.
  Stored records and model-visible profile data contain phone numbers; log redaction is
  limited to recognizable digit patterns and is not general-purpose PII sanitization.
- **Guardrails have false positives and failure modes.** Narrow input moderation reduces
  interference with symptom descriptions but does not eliminate it. A tripwire can still
  block input or replace an output reply. Non-tripwire input validation errors pass through,
  and this does not make the underlying agent model available during a model outage.
- **Phrase filtering is incomplete.** Broad blocked terms can cause false positives, and
  unlisted phrasing can pass. A reply combining a legitimate action with blocked text can
  be replaced in full. Blocks are logged with phone-pattern redaction.
- **Sessions are in memory.** Conversation context resets on restart; mother records and
  escalations remain in SQLite. There is no multi-process or production storage design here.
- **Guidance retrieval and scheduled reminders are deferred.** There is no guidance agent,
  reviewed knowledge base, background scheduler, or template-based proactive messaging.

## 8. Repository structure

```text
use-cases/mathru-phm-companion/
  agent.py                     # five agents and handoffs
  tool.py                      # identity-scoped model-callable tools
  store.py                     # SQLite registrations and escalations
  phm_registry.py              # operator-managed PHM authorization
  phm_registry.example.yaml    # empty registry template with demo instructions
  schedules.py                 # date arithmetic and validation
  danger_signs.py               # reference-table symptom matching
  escalation.py                # outbound adapter delivery and persistence
  hooks.py                     # final agent-reply language filter
  redaction.py                 # phone redaction at log-record creation
  resilient_guardrail.py       # input validation exception policy
  provenance.py                # provenance checks and status gate
  server.py / demo.py           # WhatsApp and local CLI entry points
  config.yaml / .env.example    # runtime settings and environment template
  pyproject.toml / uv.lock      # dependencies, tool settings, and locked versions
  build.sh                     # install the locked environment
  data/                        # reference data and blocked-language list
  guardrails/                  # guardrail JSON and rationale
  SPEC.md / SOURCING.md         # maintained specification and source research
  conftest.py / *_test.py       # isolated test fixtures and regression tests
```

## 9. Acknowledgements

Built for the IDEALIZE 2026 mini-competition organised by AIESEC in University of
Moratuwa, using [Agent Kernel](https://github.com/yaalalabs/agent-kernel) by Yaala Labs.
