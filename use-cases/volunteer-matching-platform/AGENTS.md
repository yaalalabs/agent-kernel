# AGENTS.md

Guidance for AI coding agents working on this use case. For the problem/solution framing and
design rationale, read [`SPEC.md`](SPEC.md) first — this file is the "how it's actually built and
what to watch out for" companion, written after implementation, not before it.

## File map

```
agent.py          profile_agent, matching_agent, the delegation-via-tool handoff between them
tool.py           search_opportunities, save_user_profile, load_user_profile, _current_user_id
data/opportunities.json   36 fictional volunteer opportunities the matching tool ranks against
demo.py           CLI entrypoint (agentkernel.cli.CLI) — no Telegram env vars needed
app.py            REST API entrypoint, serves the web frontend's API and Telegram together
telegram_handler.py  FormattedTelegramRequestHandler — renders markdown as real Telegram HTML
static/index.html Single-file web chat UI — a fully working user interface
tool_test.py      Unit tests for search_opportunities — no agent/session/LLM involved
demo_test.py      Live CLI smoke test — skipped without GOOGLE_API_KEY/GEMINI_API_KEY
config.yaml       session/logging config (no knowledgebase block — see Memory below)
```

## Framework and provider

**Pydantic AI** on **Google Gemini** (`google:gemini-3.6-flash` in `agent.py`'s `MODEL` constant),
not the OpenAI Agents SDK — chosen specifically because Google AI Studio issues a free
`GOOGLE_API_KEY` with no billing card, unlike OpenAI's current signup flow. If you ever see
`agent.py` fail with a 404 naming the model, that model was retired — check
https://ai.google.dev for the current free-tier flash model name and update `MODEL`.

**No `handoffs=` primitive.** Unlike the OpenAI Agents SDK, Pydantic AI has no built-in
agent-to-agent handoff. `profile_agent` → `matching_agent` routing is delegation-via-tool:
`hand_off_to_matching_agent()` in `agent.py` is a plain async function bound as a tool that calls
`matching_agent.run(...)` directly and returns its output. Two consequences worth knowing:
- This nested call bypasses Agent Kernel's `AgentService`/`Runtime` entirely, so it never logs
  `"Selected agent: matching_agent"` the way the outer `profile_agent` selection does — the only
  visibility into it is the explicit `_log.info(...)` calls inside `hand_off_to_matching_agent`.
- `ToolContext.get()` still works correctly inside `search_opportunities` during this nested call,
  because the context variable set at the top of the outer `PydanticAIRunner.run()` stays active
  for the whole span — it isn't re-scoped per nested agent.

## Memory: read this before touching `_current_user_id()`

`tool.py`'s `_current_user_id()` has a load-bearing comment explaining exactly why it works the
way it does — read it in full before changing it. The short version: the installed `agentkernel`
version (`0.8.1`) does **not** propagate a chat request's `user_id` down to tools (verified
directly against the installed package, not assumed from docs or the monorepo's own unreleased
source), so it falls back to `ctx.session.id`. That only gives persistence across visits if the
caller *reuses* the same `session_id`:
- **Telegram**: the `chat_id` is already stable across separate conversations with the same
  user (`telegram_chat.py` uses it as `session_id` directly), so this fallback just works, no
  special-casing needed.
- **Web frontend / CLI**: `static/index.html` deliberately persists its id in `localStorage`
  instead of generating a fresh one per page load, for the same reason. The CLI gets a fresh
  `session_id` per `demo.py` run, so CLI memory only persists within one run — acceptable, since
  the CLI is for local dev/testing, not the persistence demo. If you build another client, it
  needs to reuse a stable id the same way or memory won't work for it.
- **Slack** (attempted, not currently wired — see below) would have needed different handling:
  its `session_id` is the thread timestamp, which changes per conversation, so the code read the
  real Slack user id from `AgentRequestAny(name="body", content=body)["user"]` instead. That
  extraction is no longer used now that Slack isn't wired into `app.py`, but it's a useful
  reference if a similarly session_id-unstable channel gets added later.

If you ever upgrade the pinned `agentkernel` version and it starts supporting genuine
acting-user propagation, `_current_user_id()` can likely be simplified — but verify it against the
new version's actual source before assuming, the same way this one was.

The knowledge store is `ChromaManager` (`agentkernel.knowledgebase.chroma`), used for exact
`ids=[...]` upsert/get (not semantic search) via its `.collection` attribute directly, since the
base `KnowledgeBase.read()`/`write()` interface only exposes semantic query, not exact-key lookup.
Persisted to `./chroma_db/` (gitignored). First call on a machine downloads a small local
embedding model (one-time, no API key, needs internet).

## Telegram: confirmed working, the wired interface

`app.py` wires `FormattedTelegramRequestHandler` (not the stock `AgentTelegramRequestHandler` —
see `telegram_handler.py`) constructed unconditionally, so `AK_TELEGRAM__BOT_TOKEN` must be
non-empty for `app.py` to start (raises `ValueError` otherwise). First verified via a simulated
webhook POST to `/telegram/webhook` with a realistic payload (no real bot needed for that check),
then confirmed for real with an actual Telegram bot, a real ngrok tunnel, and a live conversation:
`Selected agent: profile_agent` → the full profile captured in one message →
`Delegating to matching_agent with profile_summary=...` → a complete ranked-match reply, with
real bold/italic formatting, delivered back through real Telegram servers.

Two things worth knowing if you touch this:
- **No identity special-casing needed.** Telegram's `session_id` is the `chat_id`
  (`telegram_chat.py`'s `_process_agent_message`), which is already stable across separate
  conversations with the same user — `_current_user_id()`'s plain `session.id` fallback handles
  it correctly (see Memory section above for why that's not always true of every channel).
- **The webhook is not auto-registered**, despite `agentkernel`'s own Telegram README claiming
  otherwise ("automatically set when your server starts") — grepped the installed
  `telegram_chat.py` directly and confirmed there's no `setWebhook` call anywhere in it. Register
  it manually with `curl "https://api.telegram.org/bot<TOKEN>/setWebhook?url=<public-url>/telegram/webhook"`
  once per public URL (not on every restart, as long as the URL — e.g. a claimed ngrok static
  domain — stays the same).
- `FormattedTelegramRequestHandler._send_message` overrides the one method every outgoing
  message funnels through (including `/start`, `/help`, and the error fallbacks) to convert
  `**bold**`/`*italic*`/`` `code` `` into Telegram's HTML formatting before sending with
  `parse_mode="HTML"`. Chose HTML over Telegram's Markdown/MarkdownV2 modes deliberately — those
  require escaping many special characters in plain text or the whole message fails to send
  ("can't parse entities"), a real risk with arbitrary LLM-generated text; HTML only requires
  escaping `&`, `<`, `>`.

## Slack: attempted, thoroughly investigated, dropped

Not currently wired into `app.py` — the project settled on Telegram instead after Slack's
webhook setup consumed disproportionate time without a resolution. The attempt ruled out
everything checkable: route live and correctly rejecting unsigned requests; OAuth scopes and
event subscriptions confirmed correctly configured and the app reinstalled in the Slack admin
UI; App Home's messages tab enabled (off by default, blocks DMs otherwise); the public tunnel
confirmed genuinely reachable from an independent client (not just curl from the same machine)
— tried across two tunnel providers (Pinggy, then ngrok with a stable claimed domain) to rule
out a tunnel-specific problem. The consistent result: Slack's one-time URL-verification
handshake (`type: url_verification`) reached the server correctly every time, on both tunnels,
but a real `message` event never did — not once. That asymmetry (verification works, live
delivery doesn't, across two different endpoints) points to something on Slack's
account/workspace side that isn't exposed by the app-configuration screens, not a missed setup
step. If picking this back up, a completely fresh Slack app (new App ID, not reinstalling the
existing one) is the next thing to try, on the chance something is stuck to this specific app's
id rather than its configuration — and re-add `AgentSlackRequestHandler` to `app.py`'s handler
list plus the `slack` extra to `pyproject.toml` (both were removed when Slack was dropped).

## Running things

See `README.md` for the full setup/run/test instructions — don't duplicate them here, they'll
drift. The one thing worth restating: `demo.py` needs only `GOOGLE_API_KEY`; `app.py` needs that
plus `AK_TELEGRAM__BOT_TOKEN` (a non-empty placeholder is fine) because of the unconditional
Telegram wiring above.

## Testing conventions

`demo_test.py` deliberately does not assert exact agent wording — it only checks for a real,
non-empty, error-free reply. If you add content-specific tests as real conversational behavior
solidifies, keep this smoke test too; it's what catches wiring regressions (broken imports, a
retired model name, a broken tool binding) independent of whatever the agents happen to say.
`tool_test.py` is the place for anything about `search_opportunities`' ranking logic — it needs no
agent, session, or API key, so there's no reason to ever gate a ranking-logic test behind a key.
