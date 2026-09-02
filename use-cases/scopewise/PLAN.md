# ScopeWise Implementation Plan

> Execute inline, task by task, with failing behavior tests before implementation. User approved the core concept and requested a deployable project. All edits stay within this use case; no commits or pushes are authorized.

**Goal:** Deliver a private, deployable syllabus-aware past-paper checker with evidence, review controls and an Agent Kernel assistant.

**Architecture:** FastAPI serves a static client and owner-scoped SQLite services. Pydantic AI agents registered in Agent Kernel use a local Ollama model; typed results are validated before persistence. Telegram links to the same account tools.

**Tech stack:** Python 3.12, FastAPI, SQLite, pypdf, Agent Kernel 0.8.1, Pydantic AI, Ollama, vanilla JS, Docker.

**Spec:** `SPEC.md`.

## Global constraints

- No mandatory paid APIs. No cloud fallback or automatic charge-bearing calls.
- One app process for the initial deployment; no horizontal-scale claim.
- All competition changes live in `use-cases/scopewise/`.
- Invalid evidence cannot become a match.
- Do not claim launch gates passed without evidence.

## Task 1 — secure records and evidence

Files: `scopewise/models.py`, `store.py`, `security.py`, `documents.py`, `matching.py`, `tests/test_core.py`, `tests/test_security.py`, `pyproject.toml`.

- [x] Write behavior tests for quoted page evidence, cross-owner reads, scrypt sessions, invalid PDFs, pack coverage, exact duplicate removal and stale scope versions. Use hand-authored source pages and literal expected objectives.
- [x] Run tests and record the missing behavior.
- [x] Implement the validated models, transactional records, bounded PDF extraction and deterministic pack service.
- [x] Rerun tests and check unauthorized/malformed branches.

## Task 2 — model pipeline and Agent Kernel

Files: `scopewise/agents.py`, `jobs.py`, `tests/test_agents.py`, `config.yaml`.

- [x] Test evidence rejection and failed jobs using injected external-model responses; all application validation remains real.
- [x] Implement structured objective/question extraction and question alignment with supplied evidence, local model only by default.
- [x] Register Pydantic AI agents in Agent Kernel; authenticated tools obtain the acting owner from server-side context.
- [x] Test at least one real local-model task and one Agent Kernel tool invocation; record actual limitations.

## Task 3 — API and review workspace

Files: `scopewise/app.py`, `static/index.html`, `static/app.js`, `static/style.css`, `tests/test_api.py`, `sample_data/`.

- [x] Write API tests for auth/CSRF, upload limits, owner isolation, scope approval, analysis review, pack generation and course deletion.
- [x] Implement the API using the task 1 services and bounded jobs.
- [x] Build the responsive upload, evidence review, coverage and pack interfaces with text-safe rendering.
- [x] Run an end-to-end browser flow and inspect screenshots; fix interaction and layout defects.

## Task 4 — Telegram and deployment

Files: `scopewise/telegram.py`, `tests/test_telegram.py`, `Dockerfile`, `compose.yaml`, `.env.example`, `README.md`, `AGENTS.md`, `DEPLOYMENT.md`, `scripts/`.

- [x] Test private-chat linking, unknown identities, replay protection and webhook authentication.
- [x] Extend the existing Agent Kernel Telegram handler for these application constraints.
- [x] Package a non-root container, persisted storage, local Ollama connection, health checks and TLS configuration example.
- [x] Run all tests, formatting, dependency checks, browser smoke and deployment preflight available locally. Document any unverified real-service gate.

## Self-review

Task 2 consumes validated models and owner-scoped records from task 1. Task 3 consumes task 1 services and task 2 jobs. Task 4 consumes task 2 assistant and task 3 auth/link records. No task modifies upstream core or examples. Security controls are enforced by application services, not by model instructions. Model and live-channel verification are separate from deterministic fixture tests.

## Verification outcome

Implemented and checked locally: 28 automated tests, lint/format, real Agent Kernel extraction and tool execution, browser upload/review/pack/versioning, mobile overflow inspection, and a non-root Linux container smoke test.

**Open release work:** local-model semantic quality is below the required standard. Real-course evaluation, live Telegram credentials/webhook, actual-host TLS/capacity, and a production restore rehearsal remain open. See `EVALUATION.md` for failed model runs; implementation completion is not production readiness.
