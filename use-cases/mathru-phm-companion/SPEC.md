# Mathru - Maternal Health Companion Specification

## Agent Description

A multi-agent WhatsApp solution that supports expectant mothers and the Public Health
Midwife (PHM) assigned to them. Mothers interact in natural language over WhatsApp to
register, learn when their next antenatal or immunisation visit is due, ask general
maternal-health questions, and report symptoms. A deterministic danger-sign screener
decides when a report must be escalated, and the system hands the case to the assigned
PHM with the mother's context attached.

The system is a triage-and-routing assistant, not a clinical decision system. All
clinical thresholds come from a fixed, human-authored reference table. The language model
handles conversation, language, and routing only.

Addresses UN SDG 3 (Good Health and Well-being), targets 3.1 and 3.2.

## Safety Constraints

These are hard requirements. Any implementation that violates them is incorrect.

- The system must never state, suggest, or rank a diagnosis, and must never name a
  medical condition as applying to the user.
- The system must never recommend, name, or dose any medication, supplement, or remedy.
- The model must never originate a clinical threshold, severity level, or triage
  decision. Severity and recommended action come only from `screen_danger_signs`.
- Any symptom classified `red` must trigger escalation to the assigned PHM in the same
  turn, and the reply must direct the mother to contact her PHM or nearest hospital
  immediately.
- The system must not attempt to reassure a mother out of seeking care. When uncertain,
  it escalates.
- Every response arising from a symptom report must carry a short standing note that the
  assistant is not a clinician.
- Personally identifying data is minimised: store the mother's first name only. Do not
  store or request NIC numbers, full names, or addresses beyond MOH division.
- Phone numbers must be redacted in all log output.

## Functional Requirements

### Agents

Build six Agent Kernel agents using the OpenAI module, with `mathru_triage` as the
entry point and the rest reachable by handoff.

- `mathru_triage` — entry agent. Detects intent and hands off. Handles greetings and
  out-of-scope messages. Never answers health questions itself.
- `intake_agent` — registers a mother: first name, MOH division, expected delivery date
  (EDD) or child date of birth, assigned PHM phone number. Confirms the record back to
  the user before saving.
- `schedule_agent` — answers questions about upcoming antenatal visits and childhood
  immunisations for the registered mother.
- `danger_sign_agent` — conducts structured symptom screening. Escalation is triggered
  inside `screen_danger_signs`, not by this agent.
- `phm_agent` — serves a sender whose number matches a registered `phm_phone`: caseload
  queries and escalation acknowledgement.
- `guidance_agent` — answers general maternal and newborn care questions from the
  knowledge base. Phase 4; see Build Order.

### Tools

Implement in `tool.py` as plain functions bound with `OpenAIToolBuilder.bind`.

No tool accepts the sender's phone number as a parameter. Every tool resolves the sender
from `ToolContext.get().session.id`, so the model cannot assert who is speaking. The one
phone number that is a parameter is `phm_phone`, a data field the mother supplies.

- `register_mother(first_name, moh_area, phm_phone, edd_iso, child_dob_iso)` — creates or
  updates the mother's record. Either `edd_iso` or `child_dob_iso` is required, not both.
- `get_mother_profile()` — returns the stored record or a not-registered marker.
- `compute_antenatal_schedule()` — returns the antenatal visit calendar derived from the
  registered mother's stored EDD as pure date arithmetic. Takes no parameters; the EDD is
  read from storage, never supplied by the model.
- `compute_immunization_schedule()` — same, from the stored child date of birth.
- `next_appointment()` — returns the single next due item and its date.
- `screen_danger_signs(symptom_text)` — matches the reported symptoms against the
  danger-sign reference table and returns matched signs, a severity of `red`, `amber`,
  or `green`, and the prescribed action string. Returns `amber` when nothing matches but
  a symptom was clearly reported. On `red` it escalates to the assigned PHM inside the
  same call; escalation is never a separate model decision.
- `resolve_role()` — returns whether the sender is a registered mother, a registered
  PHM, or neither, by comparing the session id against stored `phm_phone` values. The
  model never decides who is a PHM.
- `phm_caseload()` — returns the calling PHM's registered mothers and any open
  escalations, so a PHM can query her own caseload over WhatsApp.
- `acknowledge_escalation(escalation_id)` — marks an open escalation acknowledged.
  PHM-side only. It sends no notification to the mother.
- `search_guidance(query)` — retrieves passages from the knowledge base. Phase 4.

Escalation delivery itself is an internal function in `escalation.py`, called by
`screen_danger_signs`. It is never model-callable and is not bound as a tool.

### Danger-sign reference table

- Store as a version-controlled data file, not in code and not in a prompt.
- Each entry has: sign identifier, matching keywords and common Sinhala and Tamil
  transliterations, severity, and action string.
- Table severities are restricted to `red` and `amber`. `green` is a system-level state
  meaning no symptom was reported at all, and is never a value in the table.
- Populate from published Ministry of Health and WHO maternal and newborn danger-sign
  patient education material. Cite the sources in `README.md`.
- Matching is keyword and synonym based, evaluated in Python. The model passes through
  the mother's description; it does not choose the severity.
- The file must carry a header comment stating that the table requires clinician review
  before any real-world use.

### Conversation and memory

- The WhatsApp integration uses the sender's phone number as the session identifier.
  Rely on this for per-mother conversation continuity; do not build a parallel session
  mechanism.
- Persist mother records in a local SQLite database managed inside tool.py using the Python standard library sqlite3 module. This is tool-owned storage and is unrelated to Agent Kernel's session backend. Do not set session.type to sqlite; it is not a supported backend. Sessions stay in_memory.
- A mother must not need to re-register or restate her EDD in later conversations.

### PHM interface

- The same WhatsApp deployment serves PHMs. A sender whose number matches a registered
  `phm_phone` is routed to PHM capabilities: caseload queries and escalation
  acknowledgement. Role governs access to PHM capabilities only. A PHM who is herself a
  registered mother keeps the danger-sign path open.
- Escalation messages to PHMs must be sent to a number that has an open messaging window
  or an approved template. Document this constraint in `README.md`.

### Guardrails

- Enable Agent Kernel guardrails on the input and output paths, for moderation and
  jailbreak checks. Do not enable guardrail PII detection: a mother legitimately types her
  PHM's phone number during registration, and blocking it would break intake.
- Redact phone numbers from log output only. Redaction must never apply to the escalation
  path, which needs the PHM's real number to deliver.
- Add a post-execution hook that blocks outbound messages containing diagnosis-like or
  medication-like language. Diagnosis-like language is replaced with the standard
  escalation response; medication-like language is replaced with a response declining to
  advise on medication. The hook must not block escalation messages or danger-sign action
  strings, and every block is logged with the original reply, redacted.

## Local Development

- Provide `demo.py`, a local CLI entry point that exercises the full agent graph without
  WhatsApp, seeded with a sample mother and a sample PHM.
- Provide `server.py`, the WhatsApp entry point using `AgentWhatsAppRequestHandler` and
  `RESTAPI.run([handler])`.
- Use `uv` for dependency management. Target Python 3.12.
- Configure logging and session settings in `config.yaml`.
- Read all secrets from environment variables. Never commit tokens or keys.
- Keep virtual environments, generated dependency exports, the SQLite database, and
  installed coding-agent skills out of Git.

## Deployment

- No cloud deployment in this version. The solution runs locally with a tunnelled
  webhook, and setup instructions must be reproducible on a clean machine.
- Do not create Terraform, Lambda, or Docker assets.

## Build Order

Implement in this order. Each phase must run end to end before the next begins.

1. WhatsApp channel with a single passthrough agent, verified by a live round trip.
2. `intake_agent`, `schedule_agent`, the two schedule tools, and SQLite persistence.
3. `danger_sign_agent`, the reference table, internal escalation, PHM role routing,
   guardrails, and the post-execution hook.
4. `guidance_agent` and the knowledge base. The system
   must remain complete and coherent without it.

## Out of Scope

- Diagnosis, treatment, triage decisions made by the model, and medication advice.
- Integration with real health information systems or patient registries.
- Cloud deployment and infrastructure as code.
- A web or mobile client. WhatsApp is the only user interface.
