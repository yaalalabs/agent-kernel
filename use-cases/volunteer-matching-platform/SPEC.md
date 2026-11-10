# Volunteer Matching Platform Specification

## Agent Description

A multi-agent solution that connects individuals with suitable volunteer opportunities (SDG 17 — Partnerships for the Goals). A `profile_agent` captures the user's skills, availability, causes of interest, and location preference, then hands off to a `matching_agent`, which retrieves and ranks relevant opportunities from a provided dataset using a tool, returning the result with a brief justification per match. A knowledge store retains user preferences so returning users are recognized in later, separate conversations.

## Functional Requirements

### Agents

- Build two Agent Kernel agents using **Pydantic AI**, pointed at **Google Gemini** (`google:gemini-3.6-flash`, free tier via Google AI Studio — `GOOGLE_API_KEY` or `GEMINI_API_KEY` env var, no card required; verify this model name is still current if this is picked back up much later — Google retires older flash models on a schedule, and `gemini-2.5-flash` was already retired for new keys by the time this was written): `profile_agent` (entry point) and `matching_agent`.
- `profile_agent`:
  - On the first message of a conversation, calls `load_user_profile` to check whether this user has a stored profile.
  - If a profile exists, greets the user by referencing what's already known and asks only for anything missing or that they want to change, instead of re-asking everything.
  - If no profile exists, conversationally collects: skills (list), availability (days/hours or a free-text description), causes of interest (e.g. environment, education, health — ideally SDG-aligned), and a location or remote preference.
  - Once the required fields are gathered, calls `save_user_profile`, then calls `hand_off_to_matching_agent` with a summary of the captured profile.
- `matching_agent`:
  - Calls `search_opportunities` with the current profile's skills, causes, location, and remote preference.
  - Returns the top 3–5 ranked matches, each with a one-line justification tying the match to a specific skill or cause overlap.
  - If no opportunities score above a minimum relevance threshold, says so plainly rather than forcing weak matches.
- **Pydantic AI has no `handoffs=` primitive** (unlike the OpenAI Agents SDK) — multi-agent routing is delegation-via-tool: `profile_agent` is given a plain async tool function, `hand_off_to_matching_agent(profile_summary)`, that runs `matching_agent.run(...)` internally and returns its output. Register both agents via `PydanticAIModule([profile_agent, matching_agent])`.

### Tool

- Implement `search_opportunities(skills: list[str], causes: list[str] | None, location: str | None, remote_ok: bool) -> list[dict]` in `tool.py`.
- Reads opportunities from `data/opportunities.json` (see Dataset below).
- Deterministic scoring (not LLM-based): weight skill overlap count highest, then cause/SDG tag match, then location/remote match.
- Returns the top N (default 5) results sorted by score descending; each result includes a `justification` string generated from which fields matched (e.g. "Matches your skills in graphic design and your interest in education").
- Must be unit-testable in isolation from any agent or LLM call.

### Dataset

- `data/opportunities.json`: a list of 30–40 objects, each with:
  - `id` (string), `organization` (string, fictional/generic — not a real org's name or branding), `title` (string), `description` (string), `required_skills` (list of strings), `cause_tags` (list of strings, SDG-aligned where possible), `location` (string), `remote` (boolean), `time_commitment` (string, e.g. "2 hrs/week").
- Cover a spread of causes/skills/locations broad enough that the matching tool's ranking is visibly meaningful across different user profiles, not just returning the same top results regardless of input.

### Memory / Knowledge

- Implement `save_user_profile(skills: list[str], availability: str, causes: list[str], location: str) -> str` and `load_user_profile() -> dict | None` in `tool.py`, backed by an Agent Kernel `KnowledgeBase` (`ChromaManager` from `agentkernel.knowledgebase.chroma`) rather than plain session cache. Neither takes an explicit user id — the identity to key on is resolved internally by `_current_user_id()`, not supplied by the LLM (avoids relying on the model to correctly echo back an id it was never actually told in conversation).
- **Verified against the actual installed dependency (`agentkernel==0.8.1`), not assumed:** an earlier draft of this design planned to read `user_id` from an "acting-user" propagation mechanism (`ACTING_USER_CACHE_KEY`) — that exists only in the monorepo's unreleased `develop` source, not in 0.8.1 (confirmed directly: zero references to `acting_user` anywhere in the installed package, and `RequestBuilder._attach_additional_context` explicitly excludes `user_id` as a "known field" it won't forward). The real, verified mechanism `_current_user_id()` uses instead:
  - **Slack:** `AgentSlackRequestHandler` attaches the raw Slack event as `AgentRequestAny(name="body", content=body)` on every request; `body["user"]` is the Slack user id, which stays constant across separate conversations/threads (unlike `session_id`, which is the Slack thread timestamp and changes per conversation) — read directly from there.
  - **Web frontend / CLI:** falls back to the Agent Kernel `session.id`. This only gives cross-visit memory if the caller *reuses* the same `session_id` across visits, so the web frontend deliberately persists it in `localStorage` instead of generating a fresh one per page load (see `static/index.html`). The CLI gets a fresh `session_id` per `demo.py` run, so CLI memory only persists within one run — acceptable, since the CLI is for local dev/testing, not the persistence demo.
- Known, accepted limitation: identity is per-channel. The same person using both the web UI and Slack has two independent profiles — there is no cross-channel account linking in this version.

### User Interfaces

- **Web frontend (primary):** a static HTML/JS chat page that calls Agent Kernel's REST chat endpoint (`POST /api/v1/chat`), sending one id, persisted in `localStorage` across visits, as both `session_id` and `user_id` — see the Memory/Knowledge note above for why `session_id` is the one that actually matters. Renders the conversation as a chat thread. Enable CORS on the REST API if the frontend is served from a different origin than the API (already permissive by default in `agentkernel.api.http`).
- **Telegram (secondary, confirmed fully working — real bot, real conversation):** `FormattedTelegramRequestHandler` (`telegram_handler.py`) wired alongside the web API in the same `RESTAPI.run([...])` call — plain HTTP against the Telegram Bot API, no OAuth. A real Telegram conversation correctly captured a profile in one message, handed off to `matching_agent`, and returned a full ranked-match reply with real bold/italic formatting (not raw markdown symbols). Its `session_id` is the Telegram `chat_id`, which is already stable across separate conversations with the same user, so `_current_user_id()`'s plain `session.id` fallback works for Telegram without any special-casing. One implementation gap in the installed package worth knowing: despite `agentkernel`'s own Telegram README claiming the webhook is "automatically set when your server starts," the actual installed code (`telegram_chat.py`) has no such registration call — the webhook must be registered manually via Telegram's `setWebhook` API every time the public URL changes.
- **Slack — attempted, dropped:** thoroughly investigated (scopes, event subscriptions, reinstall, App Home, and genuine external tunnel reachability across two providers all confirmed correct), but never got a real message event delivered — only Slack's one-time URL-verification handshake ever reached the server. Not wired into `app.py`; see `README.md`'s Known Limitations for the full account.

## Local Development

- Provide a local CLI entry point (`demo.py`) for testing the agents without needing the web frontend or Telegram running.
- Use `uv` for dependency management.
- Keep generated dependency exports, deployment packages, local virtual environments, and installed coding-agent skills out of Git.
- Required environment variable: `GOOGLE_API_KEY` (or `GEMINI_API_KEY`) — get a free key with no card required at https://aistudio.google.com/apikey.
- First call to `save_user_profile`/`load_user_profile` on a machine downloads a small (~80 MB) local embedding model for the Chroma knowledge store (cached under `~/.cache/chroma/`, one-time, no API key involved) — needs internet access once, not per-profile.
- `app.py` constructs `FormattedTelegramRequestHandler` unconditionally alongside the web API handler, so `AK_TELEGRAM__BOT_TOKEN` must also be set (even to a placeholder value) for `app.py` to start at all. `demo.py` (CLI) needs none of the Telegram variables. Real end-to-end Telegram testing additionally needs a tunnel (e.g. ngrok, with a claimed stable domain) for the local webhook URL, and a one-time manual `setWebhook` API call — see README.md.

## Deployment

- Optional / stretch goal — not required for a working local solution.
- If pursued, follow the deployment folder structure used by the Agent Kernel AWS serverless examples (a single `lambda.py` entry point, packaging commands in `deploy/deploy.sh`), and keep the underlying agent and tool logic shared between local and deployed execution.
