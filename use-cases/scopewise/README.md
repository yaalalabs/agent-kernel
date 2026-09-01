# ScopeWise

**Old papers. Current perspective.**

ScopeWise helps a student decide which past-paper questions are useful for the module they are studying **now**. It compares current syllabus objectives with historical questions, shows the source evidence, separates assessment format from syllabus fit, and assembles a reviewed practice pack with visible gaps.

This is an **invite-only pilot**, built with Agent Kernel for the IDEALIZE mini competition. It supports **SDG 4: Quality Education**. It is not an exam predictor, an answer generator, or a claim that a student is exam-ready.

## The problem

A search result or an old paper does not know the boundaries of your module. Some questions are too advanced, others miss required skills. A change of lecturer adds another uncertainty: a question can remain relevant to the syllabus while asking for an answer format that no longer matches current guidance.

## The solution

1. Upload a current syllabus, current notes/slides, past papers and current assessment guidance.
2. Inspect the extracted source pages and approve the documents.
3. Ask the local agent for draft objectives and questions. Correct and approve each item with a page quote.
4. Compare approved questions against the approved objectives. Every suggestion remains unreviewed.
5. Review **syllabus fit** and **current assessment fit** independently.
6. Build a pack of reviewed suitable questions, omit exact repeats and see uncovered objectives.

Use **Start manual review** to work through the same evidence controls without model suggestions. Its origin is explicitly labeled; it is never presented as AI output.

Changing the lecturer invalidates old analyses and packs and withdraws approval from existing assessment guidance. It does **not** infer what the new lecturer will ask. Approving a replacement syllabus retires the previous syllabus and its objectives. Historical analyses remain visible as stale.

| Syllabus fit | Meaning |
| --- | --- |
| In scope | Evidence supports the selected objective and required action/depth |
| Partly in scope | Useful practice, but not full objective coverage |
| Explicitly excluded | A linked current objective explicitly excludes it |
| Needs evidence | There is insufficient evidence to decide; absence is not exclusion |

Assessment fit is separately **matches guidance**, **different format**, or **not established**. Historical papers alone cannot certify current assessment style.

## Setup and run locally

Requirements: Python **3.12 or 3.13**, [uv](https://docs.astral.sh/uv/getting-started/installation/), [Ollama](https://ollama.com/download), and sufficient memory for a downloaded model. A 16 GB Apple Silicon machine was used during development; this is not a concurrency capacity guarantee.

From this directory:

```bash
cp .env.example .env
uv sync --frozen --python 3.12
ollama pull llama3.1:latest
ollama pull nomic-embed-text:latest
# If Ollama is not already running, start it in another terminal:
ollama serve
```

Start the app in a separate terminal, from the same directory:

```bash
uv run uvicorn scopewise.app:create_app --factory --host 127.0.0.1 --port 8080 --workers 1 --no-access-log
```

Open **http://127.0.0.1:8080**. Choose **Create account**. For local development only, the invitation is `scopewise-local`; choose your own username and a password of at least 12 characters.

Click **Explore sample module** for a guided example. The sample consists entirely of original synthetic sources and **human-authored reviewed judgments**. Loading it does not call the model. Files in `sample_data/` let you demonstrate fresh uploads separately.

The local review, editing, sample and pack workflows do not require a running model. Fresh extraction, comparison and assistant responses require Ollama. Semantic source search uses the local `nomic-embed-text` model and falls back to keyword search if embeddings are unavailable. There is **no cloud fallback and no mandatory paid API**. Hardware, electricity, hosting, domain and network use can still cost money. Downloading model weights requires internet access; inference then runs locally. Only localhost and the documented private container hostnames are accepted as model endpoints.

## What happens to an uploaded file

ScopeWise does not send the document to a hosted vector service. It extracts text per PDF page or PowerPoint slide, splits each page into overlapping exact-text chunks, and stores those chunks in the same private SQLite database as the course. When local Ollama embeddings are available, normalized vectors are stored as compact binary values beside the chunks and ranked with cosine similarity plus keyword overlap. If embedding fails, upload still succeeds and search uses keyword overlap.

This is a small-course RAG design, so it does not need a separate vector database. Search retrieves a few relevant current-guidance chunks for question comparison and always preserves the original document ID, page/slide and verbatim text. Scope/objective extraction is deliberately different: it scans every chunk in bounded groups, because retrieving only the most similar passages could miss an explicit exclusion. Model references are resolved against server-supplied aliases; an unknown alias is discarded and that judgment becomes uncertain instead of aborting the whole comparison.

## Agent Kernel is on the execution path

`scopewise/agents.py` registers three Pydantic AI agents through `PydanticAIModule`:

- `scopewise_extract`: proposes source-grounded draft objectives or questions.
- `scopewise_align`: compares one question at a time using a small structured decision. The application resolves its short references to the approved objective citations, verifies guidance quotes and keeps the result unreviewed.
- `scopewise_assistant`: calls `get_course_overview`, `read_source_page`, `get_coverage_review`, and `prepare_practice_pack`.

All model work runs through **AgentService**. Tools get owner/course identity from **ToolContext** populated by the server, never from model arguments or document instructions. Course context is isolated by account/course, cleared on revision changes, and bounded to eight conversation turns before reset. Sessions are in memory; courses, documents, jobs and judgments are in SQLite.

The Telegram adapter subclasses Agent Kernel's **AgentTelegramRequestHandler**, uses its command/message dispatch and message delivery, and routes authenticated messages into the same assistant. It adds private-chat linking, a required secret, rate limits and duplicate-update protection. It does not mount the framework's unauthenticated generic agent routes.

## Telegram setup

1. Create a bot with Telegram's **@BotFather**. Do not put the token in chat, screenshots or Git.
2. Configure `.env` with `AK_TELEGRAM__BOT_TOKEN`, a random `AK_TELEGRAM__WEBHOOK_SECRET` of at least 24 characters, and your real HTTPS `SCOPEWISE_PUBLIC_URL`.
3. Restart the app. Register the webhook explicitly:

```bash
uv run python -m scripts.setup_telegram
```

4. In the web workspace select **Connect Telegram**. Send the displayed `/link CODE` to your bot in a **private chat** within ten minutes.
5. Send `/courses`, then `/use 1`. Ask about gaps or request a pack from reviewed questions. `/unlink` disconnects the account.

Codes are single-use and stored hashed. Group messages, edits and media are not accepted. Documents and approvals stay in the web workspace. Telegram can see messages sent through its platform. Linking a workspace does not make its source files publicly downloadable.

Webhook registration changes your bot configuration; it is never performed automatically. A live bot and HTTPS deployment are still required to demonstrate the competition's messaging requirement. See [Telegram's webhook documentation](https://core.telegram.org/bots/api#setwebhook).

## Verify

```bash
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
node --check static/app.js
# Requires the local model; uses only original synthetic material:
uv run python -m scripts.smoke_model
uv run python -m scripts.evaluate_model
```

The smoke script verifies structured extraction, an **actual Agent Kernel tool call**, and structured comparison. The evaluation script compares five development examples with hand-authored expected judgments and writes `output/local-evaluation.json`. These examples were used while tuning the prompt: they are **not an independent accuracy benchmark**. A quote validator checks evidence provenance, not whether a semantic judgment is correct.

See [EVALUATION.md](EVALUATION.md) for measured limitations and remaining release gates. Model suggestions may miss exclusions or over-link related concepts. Human review is mandatory; validate with your real course materials before relying on the output.

## Deployment and operation

[DEPLOYMENT.md](DEPLOYMENT.md) covers the non-root Docker container, private Ollama connection, HTTPS configuration, backup/restore and launch checklist. [DEMO.md](DEMO.md) contains the competition demo sequence. [SPEC.md](SPEC.md) records the product scope; [PLAN.md](PLAN.md) tracks implementation.

Pilot limits: 10 modules/account, 12 documents/module, 8 MB/file, 60 pages or slides/file, 100,000 extracted characters/file, bounded model context per call, 30 objectives and 50 questions/module, one active model task/process, three queued jobs, and a 15-minute job timeout. Start with **one topic and a few questions**. Scanned/handwritten PDFs, complex diagram understanding, old binary PPT files, video search and generated answers are deferred.

Data is private to each account, but SQLite is not encrypted at rest by this application. Use encrypted storage and private backups. Delete a module from settings to remove its active database records; backups and already exported packs require separate retention/deletion. This pilot has no password recovery, billing, public registration, team sharing or multi-replica support.

All changes belong to `use-cases/scopewise/`; no Agent Kernel core files are changed. Before submission, confirm the registered team requirements, upstream stars and submission instructions in the supplied competition guidelines. Do not present synthetic reviewed results as live AI results.
