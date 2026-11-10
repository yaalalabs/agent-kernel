# Volunteer Matching Platform

A multi-agent Agent Kernel solution for SDG 17 (Partnerships for the Goals) that matches volunteers to opportunities based on their skills, availability, and causes.

## Problem Statement

Volunteers struggle to find opportunities that actually fit their skills, availability, and causes they care about. Existing volunteer listing sites are search-and-browse; nothing has a conversation with you, remembers what you told it, and comes back with a short, justified shortlist instead of a wall of listings to sift through yourself.

## Solution Overview

Two Agent Kernel agents, built with **Pydantic AI** on **Google Gemini** (free tier — no API cost to run):

- **`profile_agent`** — the entry point. Recognizes returning users (via a knowledge store) and asks only for what's missing; for new users, conversationally collects skills, availability, causes of interest, and location/remote preference.
- **`matching_agent`** — once a profile is captured, ranks opportunities from a 36-entry dataset using a deterministic scoring tool (`search_opportunities`) and explains *why* each match fits, or says plainly when nothing fits well rather than forcing a weak match.

**Memory**: profiles are saved to a `ChromaManager` knowledge store, keyed by a stable identity per channel, so a returning user is recognized in a later, separate conversation instead of starting over every time.

**Interfaces**: a web chat UI (`static/index.html`) and a **Telegram bot** are both fully working — a real conversation over Telegram correctly captured a profile, handed off to matching, and returned ranked, nicely-formatted results. Slack was also attempted and thoroughly investigated, but never got real messages delivered despite everything checkable coming back correct — dropped in favor of Telegram, which worked cleanly; see [Known Limitations](#known-limitations) for what was tried.

Full technical design, including two mid-implementation corrections made after verifying against the actual installed Agent Kernel version, is in [`SPEC.md`](SPEC.md).

## Setup Instructions

1. Install [uv](https://github.com/astral-sh/uv).
2. From this directory, run `./build.sh` (creates `.venv`, installs dependencies).
3. Get a free API key (no card required) at https://aistudio.google.com/apikey.
4. Set the required environment variables (cmd.exe shown; PowerShell uses `$env:NAME = "value"`):
   ```
   set GOOGLE_API_KEY=your-real-gemini-key
   set AK_TELEGRAM__BOT_TOKEN=placeholder
   ```
   The Telegram value only needs to be *non-empty* to let `app.py` start — the handler validates that at construction time regardless of whether Telegram is actually being used. Real Telegram setup is below.

## How to Run

- **CLI (local testing, no Telegram needed):** `uv run python demo.py`
- **REST API (backs the web frontend and Telegram):** `uv run python app.py` — listens on `http://localhost:8000`. Requires both env vars above to start.
- **Web frontend** — the primary way to use this: with `app.py` running in one terminal, serve `static/` in another:
  ```bash
  cd static && python -m http.server 5500
  ```
  Open `http://localhost:5500`. (Edit the `API_BASE` constant near the top of `static/index.html`'s `<script>` if you change the API port.)

Try a full conversation: give it your skills, availability, causes, and location; it should ask only for what's missing, then hand off to a ranked shortlist with reasons. Reload the page afterward and say hello again — it should recognize you without re-asking, since your browser id is persisted in `localStorage` across visits.

## Testing

```bash
uv run pytest
```

- `tool_test.py`: unit tests for `search_opportunities`'s ranking logic — no agent, session, or LLM call involved, always runs, including regression tests that an unrelated profile gets no matches rather than padded remote listings.
- `demo_test.py`: a live CLI smoke test (skipped automatically if `GOOGLE_API_KEY`/`GEMINI_API_KEY` isn't set) — checks `profile_agent` returns a real, non-empty, error-free reply.

Note: the first call to `save_user_profile`/`load_user_profile` on a machine downloads a small (~80 MB) local embedding model for the memory store — one-time, needs internet, no API key involved.

## Telegram Setup (confirmed working)

`app.py` serves `FormattedTelegramRequestHandler` alongside the web API — same agents, tools, and memory store, with replies rendered as real Telegram formatting (bold/italic/code) instead of raw markdown symbols (see `telegram_handler.py`). No OAuth, no app reinstalls, no scopes to configure — just a bot token and a webhook URL.

1. Open Telegram, message [@BotFather](https://t.me/botfather), send `/newbot`, follow the prompts. Copy the token it gives you.
2. Set `AK_TELEGRAM__BOT_TOKEN` to that real token (replacing the placeholder), restart `app.py`.
3. Tunnel port 8000 publicly — e.g. with ngrok, which offers a free stable domain that doesn't change on restart:
   ```
   ngrok http --domain=your-claimed-domain.ngrok-free.app 8000
   ```
4. **Register the webhook manually** — despite what `agentkernel`'s own Telegram integration README says ("automatically set when your server starts"), the installed code does not actually do this; you must call Telegram's API yourself, every time the public URL changes:
   ```
   curl "https://api.telegram.org/bot<YOUR_TOKEN>/setWebhook?url=https://your-domain.ngrok-free.app/telegram/webhook"
   ```
   A `{"ok":true,"result":true,...}` response confirms it registered. As long as you keep using the same claimed domain, you only need to do this once — not on every restart.
5. Message your bot directly in Telegram (works identically from the app, web, or phone).

## Known Limitations

- **Slack was attempted and dropped in favor of Telegram.** The code (not currently wired into `app.py`) was correct and independently verified — route live, correctly rejected unsigned requests, OAuth scopes and event subscriptions confirmed correctly configured and reinstalled in the Slack admin UI, the App Home messages tab enabled, and the public tunnel confirmed genuinely reachable from the outside across two different providers (Pinggy, then ngrok with a stable domain). Despite all of that, a real message event never once reached the server — only Slack's one-time URL-verification handshake did, consistently, across both tunnels and a fully reinstalled app. That asymmetry points to something on Slack's account/workspace side outside what the app-configuration screens expose. Rather than keep chasing it, the same effort went into Telegram instead, which worked cleanly on the first real attempt — no OAuth, no reinstalls, no scopes, just a bot token and a webhook URL.
- **Memory identity is per-channel.** The web frontend and Telegram each track identity independently (a persisted browser id vs. the Telegram chat id) — the same person on both isn't recognized as one account. See `SPEC.md`'s Memory/Knowledge section for why.
- **CLI memory doesn't persist across separate `demo.py` runs** — each run gets a fresh session id. It works fine within one run, and works across visits on the web frontend (which deliberately persists its id).
- **Pinned to `agentkernel` 0.8.x.** `pyproject.toml` requires `>=0.8.1,<0.9`. The agents, tools, and memory also run on 0.9.x, but 0.9 replaced `AgentTelegramRequestHandler` with the new `TelegramInboundAdapter`/`IOHandler` integration API, so `app.py` and `telegram_handler.py` need porting before the pin can be lifted.
- Cloud deployment is out of scope for this use case — it runs locally (CLI, REST API + web frontend, Telegram).

## Status

Working end to end, verified with a real Gemini key:

- **Web frontend:** full conversation — profile captured, handed off to `matching_agent`, ranked matches with reasons returned; returning users are recognized after a reload.
- **Telegram:** verified with a real bot over real Telegram servers — `Selected agent: profile_agent` → profile captured in one message → `Delegating to matching_agent with profile_summary='Skills: coding, teaching. Availability: weekends. Causes: education. Location: Colombo.'` → a ranked-match reply with real bold/italic formatting.
- **Fresh clone:** following only this README from scratch — `build.sh`, `uv run pytest`, and `app.py` all work as documented.
- **Tests:** `uv run pytest` passes (`demo_test.py` is skipped without a Gemini key).
