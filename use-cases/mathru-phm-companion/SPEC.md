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

Build five Agent Kernel agents using the OpenAI module, with `mathru_triage` as the
entry point and the rest reachable by handoff.

- `mathru_triage` — entry agent. Detects intent and hands off. Handles greetings and
  out-of-scope messages. Never answers health questions itself.
- `intake_agent` — registers a mother: first name, MOH division, expected delivery date
  (EDD) or child date of birth, assigned PHM phone number. Confirms the record back to
  the user before saving.
- `schedule_agent` — answers questions about upcoming antenatal visits and childhood
  immunisations for the registered mother.
- `danger_sign_agent` — conducts structured symptom screening and triggers escalation.
- `guidance_agent` — answers general maternal and newborn care questions from the
  knowledge base. Phase 2; see Build Order.

### Tools

Implement in `tool.py` as plain functions bound with `OpenAIToolBuilder.bind`.

- `register_mother(phone, first_name, moh_area, edd_iso, child_dob_iso, phm_phone)` —
  creates or updates the mother's record. Either `edd_iso` or `child_dob_iso` is
  required, not both.
- `get_mother_profile(phone)` — returns the stored record or a not-registered marker.
- `compute_antenatal_schedule()` — returns the antenatal visit calendar derived from the
  registered mother's stored EDD as pure date arithmetic. Takes no parameters; the EDD is
  read from storage, never supplied by the model.
- `compute_immunization_schedule()` — same, from the stored child date of birth.
- `next_appointment(phone)` — returns the single next due item and its date.
- `screen_danger_signs(symptom_text)` — matches the reported symptoms against the
  danger-sign reference table and returns matched signs, a severity of `red`, `amber`,
  or `green`, and the prescribed action string. Returns `amber` when nothing matches but
  a symptom was clearly reported.
- `escalate_to_phm(phone, severity, matched_signs, summary)` — sends a WhatsApp message
  to the assigned PHM containing the mother's first name, MOH division, gestational week
  or child age, matched signs, and severity. Records the escalation on the mother's
  record.
- `phm_caseload(phm_phone)` — returns the PHM's registered mothers and any open
  escalations, so a PHM can query her own caseload over WhatsApp.
- `search_guidance(query)` — retrieves passages from the knowledge base. Phase 2.

### Danger-sign reference table

- Store as a version-controlled data file, not in code and not in a prompt.
- Each entry has: sign identifier, matching keywords and common Sinhala and Tamil
  transliterations, severity, and action string.
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
  acknowledgement.
- Escalation messages to PHMs must be sent to a number that has an open messaging window
  or an approved template. Document this constraint in `README.md`.

### Guardrails

- Enable Agent Kernel guardrails on the input and output paths.
- Enable PII detection and redaction for logging.
- Add a post-execution hook that blocks outbound messages containing diagnosis-like or
  medication-like language and replaces them with the standard escalation response.

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
3. `danger_sign_agent`, the reference table, `escalate_to_phm`, guardrails, and the
   post-execution hook.
4. `guidance_agent` and the knowledge base. The system
   must remain complete and coherent without it.

## Out of Scope

- Diagnosis, treatment, triage decisions made by the model, and medication advice.
- Integration with real health information systems or patient registries.
- Cloud deployment and infrastructure as code.
- A web or mobile client. WhatsApp is the only user interface.
