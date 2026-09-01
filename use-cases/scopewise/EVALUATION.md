# Verification and honest limitations

Status: competition-readiness snapshot, 2026-09-01. Read this before describing ScopeWise as production-ready.

## What was exercised

- Automated unit/API checks cover ownership, CSRF, file rejection, bounded body bytes, source quote validation, objective-specific citations, exclusion-first candidate selection, local-embedding fallback, bounded Agent Kernel provenance, change-impact history, explicit exclusions, partial coverage, duplicate removal, changing lecturers/syllabuses, no-op suppression, changing a reviewed judgment, stale exports, failed/interrupted model jobs, manual review, Telegram linking/secrets/replay, UI contracts, judge checks, and a temporary SQLite backup/restore.
- A real `llama3.1:latest` run through Agent Kernel extracted source-backed objectives and executed `get_course_overview`. The smoke script asserts the tool event; a model claiming to use a tool is insufficient.
- The desktop browser was used for account creation, loading the labeled sample, source upload/inspection/approval, objective review, pack creation, coverage-gap display and lecturer-change invalidation. The competition pass verified the Change impact card and collapsed provenance disclosure at 1280px and 390px, with no horizontal overflow or console errors and a 44px mobile primary action.
- Docker image construction completed using the frozen dependency lock. The running Linux container passed health, signup/login, sample-pack creation/export, isolated document upload, stale-pack rejection and deletion-cascade checks. The process ran as UID 10001 with a read-only root filesystem. Actual deployed-host HTTPS, messaging, GPU performance and capacity remain separate gates.

## Historical local-model baseline is not a release-quality classifier

Extraction found two required objectives in a three-item synthetic syllabus but omitted an explicit exclusion. All extracted items remained drafts.

The original batch comparison frequently omitted fields or questions; the application rejected unusable outputs or downgraded unsupported claims. A smaller per-question decision schema improved completion but did **not** establish acceptable semantic accuracy. One earlier five-question development run classified 3/5 syllabus statuses, 3/5 assessment statuses, and 2/5 objective sets as expected. It sometimes linked indexing to a primary-key objective because both were database concepts. It also missed a concrete assessment-format difference. A later explanation-first variant failed on an unknown reference after three questions. These failures were not replaced with synthetic successful output.

The competition pass added deterministic per-question candidates, direct retention of explicit exclusions, bounded local-semantic widening, unsupported-alias downgrades, and saved run provenance. `scripts.evaluate_model` now contains eight adversarial depth, prerequisite, exclusion, and unsupported-topic cases. Results from that expanded regression must be recorded below only after a fresh run; the earlier five-question counts cannot be reused as evidence for the new pipeline.

The five examples are intentionally simple, synthetic, and used during prompt development. They are not a held-out benchmark. The manual sample judgments are authored separately from inference and labeled in the UI, exports and source files.

**Do not rely on automatic judgments from the current Llama configuration.** Use the evidence review controls to correct suggestions. Manual review can be started without a model and is labeled as such. Human approval is required before a question enters a pack. The quote validator proves a quote exists at a source location; it cannot prove that the model interpreted the quote or question correctly.

A Qwen 3.5 4B local-model comparison was initiated, but its large model download is separate from completed verification. Do not describe it as tested or selected until the same checks actually run successfully.

## Next quality gate

Collect permission-cleared material from one real module: current syllabus/notes, current assessment guidance if available, and two or three past papers. Have a knowledgeable reviewer label 20–30 questions before testing. Include same-topic/different-depth questions, prerequisites that are not directly assessed, explicit exclusions, missing context, a lecturer change with and without guidance, exact repeats, and diagrams whose text extraction is incomplete.

Measure unsupported positive links, missed exclusions, objective extraction omissions, missing questions, wrong answer-format judgments, validation failures and latency. Keep source-level evidence and reviewer disagreement. Freeze model/prompt versions before a held-out run. Do not advertise a general accuracy percentage from this development fixture.

Public launch also requires the real-host checklist in `DEPLOYMENT.md`: HTTPS, a live Telegram bot, secret handling, dependency/image review, load testing, recovery and retention. No real bot messages or public deployment have been performed in this workspace.
