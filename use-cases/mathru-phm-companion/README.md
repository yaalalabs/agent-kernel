# Mathru — Maternal Health Companion

A WhatsApp agent built on Agent Kernel that supports expectant mothers and the Public
Health Midwife (PHM) assigned to them. Mothers register, ask about their upcoming clinic
visits, and report symptoms in plain language. Reports that match a danger sign are
escalated to their assigned midwife automatically.

Addresses **UN SDG 3 — Good Health and Well-being**, targets 3.1 (maternal mortality) and
3.2 (newborn and under-five mortality).

> **This is a competition prototype, not a clinical tool.** It has not been reviewed by a
> clinician and must not be used to make care decisions. Every clinical data file currently
> ships as `placeholder`, which means the system declines to give out dates and treats every
> reported symptom as an escalation. See [Data provenance](#4-data-provenance) and
> [Known limitations](#7-known-limitations).

---

## 1. Problem statement

Sri Lanka's Public Health Midwife system achieves some of the best maternal and child
health outcomes in South Asia, and it runs almost entirely on paper. A PHM tracks her
caseload through handwritten registers; a mother tracks her own care through the physical
pregnancy record and Child Health Development Record she carries to clinic.

Two gaps follow from that:

**Mothers have no way to ask a question between visits.** A schedule sits in a booklet at
home. A worrying symptom at 2am has no channel short of travelling to a facility, and the
cost of that trip means real danger signs get waited out.

**PHMs have no inbound signal.** A midwife learns that something is wrong at the next
scheduled visit, or when a mother arrives at hospital. There is no low-friction path for a
mother to raise a concern and have it reach the right person, with context, in time.

Both sides already use WhatsApp daily. The channel exists; nothing runs on it.

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
  `AgentWhatsAppRequestHandler` and `RESTAPI`.
- **Multi-agent handoffs** through the OpenAI Agents module, with `OpenAIModule`
  registering every handoff target.
- **Session memory** keyed on the sender's phone number. The WhatsApp handler sets
  `Session.id` from the sender, so per-mother conversation continuity comes from the
  framework rather than a parallel mechanism.
- **`ToolContext`** for identity resolution inside every tool.
- **Guardrails** for moderation and jailbreak detection, deliberately scoped (see
  `guardrails/README.md`). The input guardrail is a custom subclass that **fails open** when
  the guardrail service is unreachable; see section 3.
- **Post-execution hooks** enforcing the no-diagnosis and no-medication boundary on
  every outbound message. Registered on the entry agent, which is the only place a hook
  sees replies produced after a handoff.

## 3. Safety design

The system's central design claim is that **the language model never makes a clinical
judgement**. It handles conversation, language, and routing. Every decision that could
affect care is made in Python against version-controlled data.

**Severity is decided in code.** The model passes the mother's raw text to
`screen_danger_signs` and receives a severity it cannot override or re-enter.

**The system fails toward escalation.** Placeholder or unverified data, an unmatched
symptom, or an exception anywhere in matching all resolve to escalation, never to "you are
fine". `green` is only ever reached when no symptom was reported at all, and is not a value
the danger-sign table is allowed to contain.

| Condition | Severity | Escalates |
|---|---|---|
| exception anywhere during matching | `red` | yes |
| data file not exactly `sourced` | `red` | yes |
| matched a `red` entry | `red` | yes |
| matched an `amber` entry | `amber` | no |
| symptom reported, nothing matched | `amber` | no |
| no symptom reported at all | `green` | no |

**Escalation is not a decision the model makes.** `screen_danger_signs` escalates
internally on red, in the same call. There is no model-callable escalation tool, so the
model cannot fail to call it.

**Delivery failure is never silent.** A PHM's WhatsApp messaging window may be closed.
When delivery fails, the escalation is persisted as undelivered and the mother is told in
the same turn to contact her PHM or nearest hospital directly. Nothing implies help is on
the way when it is not.

**Identity comes from the channel.** No tool accepts a phone number identifying the
sender; identity is resolved from `ToolContext.get().session.id`. Role is decided by
lookup, not by the model. A sender cannot talk their way into another mother's records or
into a midwife's caseload. Role governs PHM capabilities only — a midwife who is herself
pregnant keeps her own danger-sign path open.

**Outbound language is filtered.** A post-execution hook blocks diagnosis-like and
medication-like language, with danger-sign action strings and escalation text explicitly
allowlisted so the filter can never suppress a safety message. Diagnosis blocks and
medication blocks return different responses: asking about a supplement is a benign
question and does not deserve an alarming reply.

**The safety layer cannot silence a symptom report.** Agent Kernel's built-in input guardrail
fails closed: any error during validation — a rate limit, an outage, an expired key — halts the
run and returns a generic apology, so the agent never executes. Because the guardrail sits
upstream of every safeguard here, that would silently disable danger-sign screening and
escalation for the duration of an unrelated outage. `resilient_guardrail.py` replaces it with
one that still blocks on a genuine tripwire but passes the turn through when the service is
simply unreachable, logging every occurrence. The built-in *output* guardrail already fails
open; only the input side did not.

**PII is minimised.** First name only. No NIC, no full name, no address beyond MOH
division. Phone numbers are redacted in logs, and only in logs — redaction never touches
the escalation delivery path.

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
| `data/danger_signs.yaml` | `placeholder` | **Empty.** While it stays a placeholder, every reported symptom escalates as `red`. |
| `data/blocked_language.yaml` | populated | Not clinical guidance — a list of things the system must never say. A placeholder block list would block everything or nothing, neither of which fails safe. |

When a file's status is anything other than `sourced`, the agent names which parts of the
calendar it cannot speak for rather than quietly omitting them. **No clinical value in this
repository has been reviewed by a clinician.**

`SOURCING.md` records what was verified, the dead ends, and the traps — including that the
Epidemiology Unit's current site serves that 2017 poster as its top result with 2023 file
metadata that masks its age.

## 5. Setup instructions

### Prerequisites

- Python 3.12
- [`uv`](https://docs.astral.sh/uv/)
- An OpenAI API key
- A Meta app with a WhatsApp Business Account and a phone number
- A tunnel to expose the local webhook (ngrok or equivalent)
- A second WhatsApp number to act as the PHM

### Install

```bash
cd use-cases/mathru-phm-companion
./build.sh          # uv venv && uv sync --all-extras --dev
```

### Environment

Secrets are loaded from a `.env` file via `python-dotenv`; `cp .env.example .env` and fill
it in. Exported shell variables still work and take precedence.

```bash
export OPENAI_API_KEY="sk-..."
export AK_WHATSAPP__VERIFY_TOKEN="a_string_you_choose"
export AK_WHATSAPP__ACCESS_TOKEN="meta_system_user_token"
export AK_WHATSAPP__APP_SECRET="meta_app_secret"
export AK_WHATSAPP__PHONE_NUMBER_ID="meta_phone_number_id"
export MATHRU_DB_PATH="./mathru.db"     # optional
```

Use a permanent System User access token. The 24-hour token from the API Setup panel will
expire mid-session.

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
uv run demo.py                      # unregistered sender, exercises intake
uv run demo.py --seed               # pre-registered mother and PHM
uv run demo.py --session-id 947XXXXXXXX
```

`demo.py` drives `AgentService` directly rather than `CLI.main()`, because the built-in CLI
generates a fresh uuid4 session id per run and every tool resolves identity from the session.

### WhatsApp

```bash
uv run python server.py             # terminal 1
ngrok http 8000                     # terminal 2
```

Then message your business number.

### End-to-end walkthrough

1. From the mother's phone, send a greeting. Complete registration, giving the second
   number as the PHM. Confirm when asked.
2. Ask when the next clinic visit is due.
3. Report a symptom. The escalation is attempted immediately.
4. From the PHM's phone, query the caseload and acknowledge the escalation.

To see delivery-failure handling, run step 3 before the PHM number has ever messaged the
business number: its 24-hour messaging window is closed, the escalation persists as
undelivered, and the mother is told to make contact directly.

At step 2, expect the agent to say it cannot give dates yet and to name which parts of the
calendar are unavailable. That is the placeholder guard working, not a bug.

### Tests

```bash
uv run pytest
```

Every safety rule in section 3 has a corresponding test, in both directions where that
matters: the hook is tested for blocking unsafe language *and* for never suppressing a
danger-sign action string, and log redaction is tested for masking phone numbers *and* for
leaving the escalation delivery path untouched.

## 7. Known limitations

- **No clinician review.** No clinical value in this repository has been reviewed by a
  qualified clinician. All six clinical files ship as `placeholder`: immunisation,
  developmental screening, vitamin A and supplementation have values captured but
  unverified against a current primary source; antenatal and danger signs are empty.
  Nothing is `sourced`, so the system currently gives out no dates and escalates every
  reported symptom.
- **Vitamin A has an unresolved source conflict.** Two official readings disagree on the
  interval — 6-monthly against roughly 12-monthly. The file records both.
- **PHM assignment is free text.** A mother types her midwife's number at registration.
  Format and self-assignment are validated, but a wrong number sends her escalation to a
  stranger. In production this would come from the MOH division registry.
- **Escalations include a verbatim excerpt** of the mother's own words. A midwife needs
  her phrasing to judge urgency, so this is deliberate, but it means her description
  leaves the system in plain text.
- **Moderation is deliberately narrowed.** Broad input moderation could block a symptom
  report — "heavy bleeding" is plausibly flagged — which would bypass the entire
  fail-toward-escalation design. Categories were restricted to those that cannot
  plausibly fire on a symptom report. See `guardrails/README.md`.
- **Guardrail PII detection is disabled.** It flags phone numbers, which would break
  registration and the escalation path. PII redaction is implemented separately, for logs
  only.
- **The input guardrail fails open.** When the guardrail service is unreachable, a message
  reaches the agent unscreened. That is a deliberate trade: an unscreened message is a lesser
  harm than a symptom report silently dropped because a moderation endpoint was rate-limited.
  Every occurrence is logged as an error.
- **Guardrails roughly triple the API calls per turn.** Moderation and jailbreak checks are
  each a separate round trip on top of the agent call, and each retries on failure. Budget for
  that, or disable `guardrail.input.enabled` while iterating locally.
- **The block list is not exhaustive.** Broad terms like `mg` and `dose` will produce false
  positives, which is why every block is logged with the original reply, redacted, so the
  rate is measurable.
- **Outbound messaging is not framework-supported.** Agent Kernel exposes no public API
  for sending a message to a third party outside a request turn, so escalation calls the
  WhatsApp Cloud API directly. Raised upstream as a discussion.
- **Sessions are in-memory.** Conversation context resets when the server restarts.
  Mother records and escalations persist in SQLite.
- **No knowledge base.** A retrieval layer over Ministry of Health guidance was scoped
  and deliberately not built. Shipping an unreviewed corpus in this domain would
  contradict the safety design above.
- **Reminders are conversational, not scheduled.** Unprompted outbound messages require
  an approved WhatsApp template outside the 24-hour window.

## 8. Repository structure

```
use-cases/mathru-phm-companion/
├── agent.py              # five agents and their handoffs
├── tool.py               # model-callable tools
├── store.py              # SQLite persistence
├── schedules.py          # date arithmetic and validation
├── danger_signs.py       # table loading and severity matching
├── escalation.py         # payload, delivery, persistence — not model-callable
├── hooks.py              # post-execution language filter
├── redaction.py          # log filter
├── resilient_guardrail.py # input guardrail that fails open on service outage
├── provenance.py         # the sourced/placeholder contract for clinical data
├── server.py             # WhatsApp entry point
├── demo.py               # local CLI
├── data/                 # clinical reference data with provenance headers
├── guardrails/           # guardrail configuration and rationale
├── SPEC.md               # coding-agent-readable specification
├── SOURCING.md           # verified sources, dead ends, and stale-document traps
└── *_test.py             # tests
```

## 9. Acknowledgements

Built for the IDEALIZE 2026 mini-competition organised by AIESEC in University of
Moratuwa, using [Agent Kernel](https://github.com/yaalalabs/agent-kernel) by Yaala Labs.
