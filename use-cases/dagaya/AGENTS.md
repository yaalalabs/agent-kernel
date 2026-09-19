# Dagaya — Agent & Contributor Guide

This document is scoped specifically to the Dagaya use case. It covers the internal multi-agent topology, tool contracts, state management rules, and Dagaya-specific coding conventions that contributors and AI coding agents need to work on this use-case safely.

For repo-wide conventions (commit format, PR process, testing, CI), refer to the root [AGENTS.md](../../AGENTS.md) and [CONTRIBUTING.md](../../CONTRIBUTING.md).

---

## 1. File Map

| File | Role | Description |
|---|---|---|
| `agent.py` | **CORE** | System prompts, tool bindings, and handoff graph for all 4 agents |
| `tools.py` | **TOOLS** | All Python functions the LLM can call, including the content guardrail |
| `server.py` | **PROD** | Production web server — handles incoming Meta WhatsApp webhooks |
| `demo.py` | **TESTING** | Local CLI environment to test agent routing without WhatsApp |
| `config-whatsapp.yaml` | **CONFIG** | Links the webhook server to WhatsApp credentials; sets entry agent |
| `config.yaml` | **CONFIG** | Baseline Agent Kernel config for local CLI testing |
| `pyproject.toml` | **BUILD** | Python project dependencies managed by `uv` |
| `build.sh` | **BUILD** | One-line install script for production deployments |
| `.env.example` | **DOCS** | Template for all required environment variables |

---

## 2. Multi-Agent Topology

Dagaya operates on a strict **Hub-and-Spoke** topology. Respect these boundaries when modifying agent behavior:

1. **`dagaya_triage` (The Hub)**: Acts *only* as a router. Detects language (English, Sinhala, Tamil, Hindi) and hands off to the correct spoke. Tools: `set_preferred_language`, `set_student_context`, `get_student_profile`. **Must never answer educational queries directly.**

2. **`dagaya_tutor` (The Explainer)**: Strict Socratic tutor — never gives direct homework answers. Uses `get_student_profile` to ground all explanations in the student's country and target exam. Uses `get_curious_fact`, `search_online`, and `search_images_online` to enrich responses.

3. **`dagaya_quiz` (The Tester)**: Asks exactly one multiple-choice question at a time. Uses `generate_quiz_topic` to structure the quiz and saves results via `update_student_progress`. Available tools: `get_student_profile`, `search_online`, `search_images_online`.

4. **`dagaya_track` (The Analyst)**: Reads accumulated scores via `get_student_profile` and delivers motivational progress reports. **Never teaches, explains, or quizzes.**

All spokes have bidirectional handoff links — conversations can flow naturally between any two agents.

---

## 3. Content Guardrail

`tools.py` exposes `check_guardrail(message: str)` — a zero-latency, zero-API-cost regex filter that runs **before any LLM call**. It blocks messages containing violence, adult content, or hate speech, and returns an immediate safe reply.

- **`server.py`**: Calls `check_guardrail` inside the custom `DagayaWhatsAppRequestHandler._handle_message()` override.
- **`demo.py`**: Calls `check_guardrail` at the top of the interactive input loop before dispatching to the agent.

Do not remove or bypass this guard. It is a child-safety requirement.

---

## 4. Internet-Connected Tools

These tools give Dagaya real-time factual grounding and visual learning — critical for a tutoring system.

### `search_online(query: str, ctx: ToolContext) → str`
- **Purpose**: Live web search via DuckDuckGo (no API key required).
- **Returns**: Top 3 result snippets as a plain string for the LLM to reason over.
- **Used by**: `dagaya_tutor`, `dagaya_quiz`
- **Trigger**: Agent is not confident about a fact, needs current events, or needs to verify data.

### `search_images_online(query: str, ctx: ToolContext) → str`
- **Purpose**: Fetches a direct, embeddable HTTPS image URL for the query.
- **Returns**: A raw image URL (e.g. `https://example.com/photo.jpg`) or `"No compatible images found"`.
- **Used by**: `dagaya_tutor`, `dagaya_quiz`
- **Trigger**: Student asks to *see* something (diagrams, photos, animals, etc.). The agent places the URL as the **very first line** of its reply so `server.py` sends it as a native WhatsApp image message before the text.
- **Anti-hallucination rule**: Agents must **never** fabricate image URLs. If the tool returns `"No compatible images found"`, the agent replies in plain text only.

---

## 5. State Management

All cross-turn student data is persisted through the Agent Kernel session, not via global variables.

- **Read/Write interface**: `ToolContext.get().session.get_non_volatile_cache()` inside `tools.py`
- **Data schema**:
  ```json
  {
    "student_profile": {
      "name": "Charaka",
      "country": "Sri Lanka",
      "exam": "GCE O/L",
      "preferred_language": "en",
      "quiz_history": {
        "science": [{"score": 3, "max_score": 5}]
      },
      "weak_topics": ["science"]
    }
  }
  ```
- **Session backend**: `in_memory` for local testing. Swap to `redis` in `config-whatsapp.yaml` for stateful multi-user production deployments.

---

## 6. Coding Conventions (Dagaya-Specific)

- **Async/Await**: All tool functions and server handlers are fully async. New network calls must use `async def` + `await`.
- **WhatsApp Formatting**: All agent output must use WhatsApp's native format — `*bold*`, `_italic_` — never Markdown headers or LaTeX.
- **Dependencies**: Add new packages via `uv add <package>` which updates `pyproject.toml` automatically.
- **Environment variables**: Never commit `.env`. Only update `.env.example` with new keys.

---

## 7. Running Locally

```bash
# Install dependencies
./build.sh

# Test agents interactively (no WhatsApp required)
uv run python demo.py

# Run the production webhook server
uv run python server.py
```
