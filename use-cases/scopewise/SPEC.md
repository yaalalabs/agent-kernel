# ScopeWise — syllabus-aware practice, with evidence

## Purpose and agreed scope

Build the past-paper scope checker selected by the user on 2026-08-31. Target a deployable private classroom pilot within two days, without mandatory paid APIs. This is an SDG 4 use case, not an exam predictor, marking service, or answer generator. All competition changes live in `use-cases/scopewise/`, matching the repository's existing directory and the booklet's scoring section.

## User journey

1. Join an invite-only deployment and sign in. Each account owns separate course workspaces.
2. Create a course and upload a syllabus, notes, and past papers as text PDFs, PPTX slides, Markdown, or text. Preserve source pages/slides. Chunk and index exact text locally for hybrid semantic/keyword retrieval. Reject encrypted, oversized, and unreadable/scanned documents with useful instructions; do not silently invent OCR text.
3. Ask the agent to extract objectives from the selected syllabus and questions from a paper. Extraction returns drafts with exact source quotes. Review/edit and explicitly approve them before analysis. An absent topic is not proof of exclusion.
4. Compare approved questions with the current approved objectives. A model proposes alignments, depth differences and uncertainty; application code validates IDs, page references, and verbatim evidence. Invalid evidence cannot become a match.
5. Review a matrix of aligned, partial, beyond-scope, and uncertain questions. Beyond-scope requires explicit exclusion evidence; otherwise classify as uncertain. Human decisions are separate from model suggestions.
6. Assemble a practice pack of approved/reviewed suitable questions, reducing exact repeats while covering objectives within a selected question count. Show uncovered objectives; do not imply complete readiness or predict examination content.
7. Revising the syllabus invalidates old analysis and packs. Keep historical analysis linked to the scope version; do not overwrite a prior scope's interpretation.
8. Use the same course tools through Agent Kernel in the web assistant and a linked Telegram private chat. A one-time linking code joins the authenticated account to Telegram; no caller-supplied owner IDs are trusted.

### Lecturer changes and assessment drift

User explicitly requested handling lecturer changes. Store the current lecturer label on a course and optional lecturer/year provenance on each paper. Treat lecturer labels as context, never as evidence that a future exam will change. Maintain two judgments: syllabus fit and assessment-style fit. Current lecturer guidance (sample paper, rubric, tutorial expectations, explicit announcements) can support a style judgment; older paper patterns alone cannot. Without current guidance the result must say `unknown`, even if the lecturer name is unchanged. Different lecturer provenance never automatically excludes an otherwise useful practice question. Style differences should identify the concrete distinction (e.g. explain vs calculate, worked application vs proof) with current-guidance page evidence. Updating the current lecturer or guidance advances the assessment version and makes existing packs stale. Scope and assessment versions are stored separately. No predictions of future questions or instructor behavior.

## Architecture

- Python 3.12–3.13; FastAPI and a small static HTML/CSS/JS client served from one origin.
- SQLite with WAL, foreign keys, per-operation transactions, owner-scoped queries, durable sessions and job records. One app process for the initial deployment; no horizontal-scale claim.
- Agent Kernel 0.8.1 with Pydantic AI. Ollama local `llama3.1:latest` is the default model endpoint. No cloud fallback or automatic charge-bearing calls.
- Agent tools read source pages, retrieve approved objectives/questions, explain evidence, and prepare a pack. Deterministic application services own access controls, evidence validation, scope versions and pack selection.
- Structured model tasks for extraction and alignment, bounded input and output sizes, timeouts, one active analysis per process, persisted job status. A failed model produces a failed job, never a fabricated successful analysis.
- Telegram uses Agent Kernel's existing handler, extended inside this use case for identity linking and bounded private-chat access. Tokens are environment configuration; public webhooks require a secret and reject replayed update IDs.
- Docker app, persistent volume, optional Ollama container, and a TLS reverse-proxy example. Never expose Ollama publicly. Provide backup/restore and deployment preflight instructions.

## Safety and operational requirements

- Invite-only signup, scrypt password hashes, random opaque hashed session tokens, expiry/logout, HttpOnly cookies, SameSite strict, Secure cookies in production, and an explicit CSRF header for mutations.
- Enforce workspace ownership on every document, question, analysis, pack, download and tool lookup. Source content is untrusted data and cannot set identity, call arbitrary tools, or trigger network fetches.
- Limit file bytes, page counts, extracted text, document count, requests and model concurrency. Do not log source content, passwords, session cookies or provider secrets.
- No remote URLs or shell execution tools. User content is not sent to third-party model services by default. Make local/model status visible.
- Plain text rendering/escaped HTML, restrictive security headers, no CDN scripts, no public signup or debug endpoints in production.
- Course deletion removes its data. Practice export uses references and question excerpts from materials the user supplied; users must have permission to use them. No public repository of uploaded papers.
- All sample course data is original synthetic material and labelled. Demo results are human-reviewed fixtures, not claims about model accuracy.

## Acceptance and launch gates

Automated checks must cover cross-account access, CSRF, invalid evidence, missing/partial coverage, repeated questions, stale packs after scope changes, unreadable files, model unavailability, and Telegram identity/replay handling. A real local-model smoke test must validate structured extraction/alignment and an Agent Kernel tool call. A browser check must exercise upload/review/pack/export and narrow-screen layout.

Deployment-ready means configuration and documented operation are reproducible. Public production readiness additionally needs a real-material evaluation, a functioning HTTPS host, Telegram credentials and a live webhook test, a model capacity/load test, and an exercised backup/restore. Do not claim these gates passed without evidence. Do not commit, push, publish or create paid infrastructure without the authorization required by repository guidance.

## Deferred

Handwriting and mathematical-diagram OCR, arbitrary LMS ingestion, YouTube analysis, model-generated answers, predictive exam scores, billing, organisation-wide sharing, and multi-replica operation.
