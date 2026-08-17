# Disaster Response & Resource Coordination Agent

**SDG 11 - Sustainable Cities and Communities · SDG 13 - Climate Action**

A multi-agent system, built on [Agent Kernel](https://kernel.yaala.ai), that coordinates
emergency resource requests and offers during disasters (floods, etc.) without manual message
tracking.

## Problem

During floods and other disasters, needs ("we need drinking water in Galle") and offers ("we
have 50 food packs available in Colombo") arrive as free-form messages from field workers,
volunteers, and community groups across many uncoordinated channels. Nobody has a single live
picture of what's needed where, what's available where, which requests are most urgent, or
which needs and offers should actually be paired up and dispatched to each other - and
duplicate reports of the same ongoing need routinely get logged as separate items. This wastes
scarce volunteer time and delays help reaching the people who need it most.

## Why Agentic AI?

The hard part of this problem isn't storage - it's the free-form text at the front of it.
Field messages are inconsistent, incomplete, and context-dependent ("elderly couple needs
medicine urgently in Matara, no transport" packs in a resource type, an urgency signal, a
region, and a logistics constraint, all in one sentence, with nothing structured about it).
A rules/regex system breaks constantly on real-world phrasing; a raw LLM call with no structure
hallucinates urgency scores and invents matches. Agentic AI is the middle ground: an LLM does
what it's actually good at - reading messy natural language and deciding what to do next - while
every judgement call that needs to be consistent and auditable (urgency scoring, match ranking,
duplicate detection) is a deterministic tool, not a model guess. The agent decides *when* to
call `score_urgency`; the tool, not the model, decides *what* the score is.

## Why Agent Kernel?

Agent Kernel is what turns "three separate LLM calls" into an actual pipeline. It gives this
project:
- **Handoffs** - `intake_agent` can hand a conversation straight to `priority_matching_agent`
  and then to `dedup_dispatch_agent` without the caller (CLI, REST API, or eventually
  WhatsApp/Slack) needing to orchestrate that itself.
- **A framework-agnostic tool-binding layer** (`OpenAIToolBuilder.bind(...)`) so the same
  `tool.py` functions work as OpenAI Agents SDK tools without extra glue code.
- **One shared entry point convention** - `demo.py`, `api.py`, and (later) a Lambda/webhook
  entry point all just import the same `AGENTS` from `agent.py`, so local dev, the REST API,
  and a future messaging-platform integration never drift out of sync with each other.
- **Built-in session memory and a test harness** (`agentkernel.test.Test`) that drives the real
  agents conversationally, so end-to-end behavior can be tested the same way a user would
  actually trigger it.

In short: Agent Kernel lets the specialized agents coordinate through handoffs while the same
underlying agent/tool code integrates cleanly with local CLI use, a REST API, external
communication channels, and a shared memory layer - without rewriting orchestration logic for
each surface.

## Architecture

One incoming message flows through three agents in a single turn, via handoffs:

```
"Elderly couple needs medicine urgently in Matara, no transport"
        │
        ▼
┌─────────────────────┐   parses free text into intent / resource / qty / location /
│   Intake Agent       │   transport signal
│                      │   tools: submit_intake, get_region_status
└─────────┬────────────┘
          │ handoff
          ▼
┌─────────────────────┐   scores urgency (vulnerable-group indicators) and matches open
│ Priority & Matching  │   needs <-> available offers ACROSS ALL REGIONS, ranked by quantity
│ Agent                │   coverage, proximity/distance, and transport compatibility
│                      │   tools: score_urgency, match_resources
└─────────┬────────────┘
          │ handoff
          ▼
┌─────────────────────┐   checks memory for an existing pending request/offer in the
│ Dedup & Dispatch     │   same region (avoids duplicates), creates/merges the record,
│ Agent                │   and dispatches a (dummy) WhatsApp notification to the match -
│                      │   flagging cross-region matches with the approximate distance
│                      │   tools: check_pending_duplicates, finalize_record,
│                      │          dispatch_notification
└──────────────────────┘
```

Memory (open requests/offers per region) lives in a process-global store in `tool.py`
(`_STATE`), scoped by **region**, not by chat session - because a disaster response spans many
volunteers, donors, and sessions over the full duration of the event. It persists for as long
as the process runs, whether you're using the CLI or the REST API.

## Agent Responsibilities

| Agent | Responsibility |
|---|---|
| `intake_agent` | Parses a free-form message into structured fields (need/offer, resource type, quantity, unit, region, contact), or answers a region status/tracking question directly. Default/entry agent. |
| `priority_matching_agent` | Scores urgency for needs (resource criticality + vulnerable-group indicators + quantity), then finds candidate matches across all regions, ranked by quantity coverage, proximity, and transport compatibility. |
| `dedup_dispatch_agent` | Checks memory for an existing open record of the same need/offer in the same region, merges into it or creates a new one, and dispatches a WhatsApp notification to the best match - flagging cross-region matches explicitly. |

## Tool Responsibilities

All tools live in `tool.py` and are deterministic - the agents decide *when* to call a tool and
*what to say* about the result, but the scoring/matching logic itself is plain Python, so it's
consistent and independently testable (see `tests/test_tool_layer.py`).

| Tool | Used by | Does |
|---|---|---|
| `submit_intake` | intake_agent | Records a structured intake; canonicalizes resource_type through a synonym table ("food"/"food packs"/"meals" all become the same category); detects a transport/logistics signal ("no transport", "can deliver") from the raw message text. |
| `get_region_status` | intake_agent | Returns all open requests/offers for a region, for tracking questions. |
| `score_urgency` | priority_matching_agent | Combines resource criticality, quantity, and detected vulnerable-group keywords into a 0-100 urgency score and band. |
| `match_resources` | priority_matching_agent | Searches the opposite pool across all regions; scores each candidate on quantity coverage, proximity (approximate road distance), and transport compatibility. |
| `check_pending_duplicates` | dedup_dispatch_agent | Looks for an existing open record of the same resource_type in the same region. |
| `finalize_record` | dedup_dispatch_agent | Creates a new record, or merges into a duplicate (summing quantity, taking the higher urgency score, adopting a positive transport signal). |
| `dispatch_notification` | dedup_dispatch_agent | Simulates (or, if configured, sends a real) WhatsApp notification to the matched party; flags cross-region matches with the approximate distance. |

## Memory Design

- **Session memory** (Agent Kernel's built-in, per-conversation) is used for normal chat
  context within one CLI/API session - `config.yaml` currently sets `session.type: in_memory`.
- **Disaster-response state** itself (open requests/offers, region by region) is intentionally
  **process-global**, not session-scoped (`tool.py`'s `_STATE` dict) - a disaster spans many
  users/sessions over days, so this memory needs to be shared across every session, not private
  to one conversation.
- Current implementation: an in-process Python dict, fine for a local demo but lost on restart
  and not shared across multiple running instances.
- **Ready for persistence**: the architecture is designed to swap `_STATE` for Agent Kernel's
  Redis/DynamoDB/CosmosDB-backed session storage (see `agent-kernel/examples/memory`), keyed by
  region instead of by session id - so the same shared "disaster state" would survive restarts
  and be visible to every process/instance handling traffic for that disaster. This hasn't been
  wired up yet (see Limitations), but nothing in the agent/tool split needs to change to do it.

## SDG Alignment

- **SDG 11 - Sustainable Cities and Communities**: helps communities coordinate emergency
  resources and respond to hazards faster, with less duplicated effort.
  reduce disaster-related economic loss and disruption to essential services.
- **SDG 13 - Climate Action**: floods and other climate-related disasters are the direct
  scenario this project targets; faster, better-coordinated relief response is part of climate
  change adaptation and disaster resilience.

## What's dummy vs. what's real integration later

| In this repo (dummy)                          | Swap in later                                                 |
|------------------------------------------------|----------------------------------------------------------------|
| `tool.py`: `_STATE` in-memory dict              | Redis / DynamoDB / Cosmos DB (`agent-kernel/examples/memory`) |
| `tool.py`: `VOLUNTEER_DIRECTORY` list           | Real donor/volunteer CRM or registration system                |
| `tool.py`: `REGION_DISTANCE_KM` hand-entered table | A geocoding/routing API (e.g. Google Maps Distance Matrix)  |
| `tool.py`: `dispatch_notification()`            | **Already wired to real WhatsApp Cloud API - see below**       |

Seed offers (drinking water in Galle, food packs in Colombo, and a deliverable medicine offer
in Ratnapura) are pre-loaded in `tool.py` so the first thing you try can immediately find a
match - including a cross-region, transport-aware match.

## Connecting WhatsApp for real dispatch notifications

`dispatch_notification` can send real WhatsApp messages via Meta's Cloud API instead of
simulating them. It's off by default (dummy mode) so nothing sends until you turn it on.

### 1. Get WhatsApp Business Cloud API credentials

You'll need a Meta Developer account with a WhatsApp Business app configured. Follow
`agent-kernel/ak-py/src/agentkernel/integration/whatsapp/README.md` for the full setup, or
Meta's own guide at https://developers.facebook.com/docs/whatsapp/cloud-api/get-started.
You need:
- **Phone Number ID**
- **Access Token** (permanent, not the 24h test token, for anything beyond quick testing)
- Optionally the API version (defaults to `v21.0`)

While testing, add the volunteer/donor phone numbers in `VOLUNTEER_DIRECTORY` /
`_seed_demo_data()` in `tool.py` as **verified test recipients** in the Meta Developer sandbox,
or use your own phone number there while you test.

### 2. Set environment variables and enable it

```powershell
$env:WHATSAPP_ENABLED = "true"
$env:AK_WHATSAPP__ACCESS_TOKEN = "your_permanent_access_token"
$env:AK_WHATSAPP__PHONE_NUMBER_ID = "123456789012345"
# $env:AK_WHATSAPP__API_VERSION = "v21.0"   # optional
python demo.py
```

```bash
# macOS/Linux
export WHATSAPP_ENABLED=true
export AK_WHATSAPP__ACCESS_TOKEN="your_permanent_access_token"
export AK_WHATSAPP__PHONE_NUMBER_ID="123456789012345"
python demo.py
```

With `WHATSAPP_ENABLED` unset (or `false`) - **demo mode** - `dispatch_notification` keeps
working exactly as before, just without actually sending - the tool result's
`whatsapp_send_result.sent` field will be `false` with a reason explaining why. Flip
`WHATSAPP_ENABLED=true` with real credentials to switch to **real mode**; the distinction is a
single environment variable, not a code change, and is always visible in the tool result so you
can tell at a glance whether a message was actually delivered or only simulated.

### Important: the 24-hour session window

Meta's Cloud API only allows plain free-form text messages to a phone number that has
messaged your business number within the last 24 hours, **or** to verified test recipients in
the sandbox. For real, cold outbound to volunteers/donors who haven't messaged you first,
Meta requires a pre-approved **message template** instead of plain text - otherwise the send
will fail with an API error (you'll see this surfaced in `whatsapp_send_result.reason`). If you
hit this, create and get a template approved in the Meta Business dashboard, then switch
`_send_whatsapp_message` in `tool.py` over to send template messages instead of plain text.

## Setup

Requires Python 3.12+ (Windows: use `uv venv --allow-existing` + `uv sync --all-extras` in place
of `./build.sh`, since it's a bash script - see "Windows notes" below).

```bash
./build.sh
cp .env.example .env
# edit .env and set GEMINI_API_KEY (from https://aistudio.google.com/apikey)
```

### Keeping your environment variables in one place

Rather than typing `$env:GEMINI_API_KEY = "..."` (or `export ...`) every terminal session, put
everything in a **`.env`** file once - `agent.py` loads it automatically on startup via
`python-dotenv`, so `python demo.py` / `python api.py` / `pytest` all just pick it up with no
extra steps. Copy `.env.example` to `.env` and fill in your real values:

```
GEMINI_API_KEY=your_gemini_api_key_here
# GEMINI_MODEL=gemini-3.1-flash-lite

# WHATSAPP_ENABLED=true
# AK_WHATSAPP__ACCESS_TOKEN=your_whatsapp_access_token_here
# AK_WHATSAPP__PHONE_NUMBER_ID=your_phone_number_id_here
```

`.env` is already listed in `.gitignore`, so it's never committed - only `.env.example` (with
no real values) is tracked in the repo. A real environment variable you've already set with
`$env:`/`export` always takes priority over the same key in `.env`, if both are present.

All agents run on Google's **Gemini API** via LiteLLM's native Gemini integration (the OpenAI
Agents SDK's officially supported way to use non-OpenAI models) - nothing else in `tool.py`,
`demo.py`/`cli.py`, or `api.py` needs to change. `GEMINI_API_KEY` is required; `agent.py` raises
a clear error at startup if it's missing.

This deliberately does **not** use Gemini's OpenAI-compatible endpoint
(`generativelanguage.googleapis.com/v1beta/openai/`). Google's newer API keys (prefixed `AQ.`,
issued by AI Studio since mid-2026, replacing the older `AIza...` format) are currently unreliable
against that specific endpoint - requests can fail with spurious auth/model errors even though the
key is valid. Routing through LiteLLM instead calls Gemini's native API, which works correctly
with both key formats.

**Note:** this pipeline leans heavily on tool calling and agent handoffs, so use a Gemini model
that's known to be good at function calling. The default, `gemini-3.1-flash-lite`, is Google's
GA (since May 2026) low-latency, cost-efficient model built specifically for high-volume
agentic workflows including tool calling and orchestration. `gemini-2.5-flash` and
`gemini-2.5-pro` are solid fallbacks if you want to compare quality/cost trade-offs.

### Rate limits (429 errors)

A single user message triggers up to 3 chained LLM calls (one per agent in the handoff chain),
so sending messages quickly on a free-tier `GEMINI_API_KEY` can hit Gemini's requests-per-minute
quota. `agent.py` configures automatic retry with exponential backoff (via the OpenAI Agents
SDK's built-in `ModelSettings.retry`) for HTTP 429 and 5xx errors - up to 5 retries, 1-20s delay
with jitter - so a transient rate limit is retried transparently instead of failing that turn.
If you still see `Error: Too many requests` after that, either wait a bit longer between
messages or check your quota/tier at https://aistudio.google.com/apikey.

### Windows notes

- `build.sh` is a bash script and won't run in PowerShell. Run its two commands directly instead:
  `uv venv --allow-existing` then `uv sync --all-extras`.
- Easiest: use a `.env` file (see above) so you never need `$env:`/`export` at all. If you do
  want to set a variable for just the current terminal session, PowerShell's syntax is
  `$env:GEMINI_API_KEY = "..."`, not `export` (that's bash-only) - but it only lasts until you
  close that terminal window, which is exactly what `.env` avoids.
- After `uv sync`, activate the venv (`.venv\Scripts\activate`) before running `python demo.py`,
  or call `.venv\Scripts\python.exe demo.py` directly - otherwise Windows falls back to your
  system Python, which won't have the project's dependencies installed.
- `agentkernel`'s CLI imports the Unix-only `readline` module for input history. On Windows,
  install the drop-in replacement first: `uv pip install pyreadline3`.

## Testing

- **`tests/test_tool_layer.py`** - deterministic, LLM-free unit tests covering intake
  extraction, urgency scoring, resource matching (quantity/distance/transport), duplicate
  detection, merge behavior, and dispatch/notification behavior. No API key needed, runs
  instantly:
  ```bash
  uv run pytest tests/test_tool_layer.py -v
  ```
- **`tests/test_agent_e2e.py`** - drives the real agents conversationally through Agent
  Kernel's test harness (`agentkernel.test.Test`), talking to Gemini for real. Requires a live
  `GEMINI_API_KEY` and is skipped automatically if one isn't set:
  ```bash
  uv run pytest tests/test_agent_e2e.py -v
  ```
- Run everything: `uv run pytest -v`. Comparison mode for the test harness (`fuzzy` by default)
  is configured in `test-config.yaml`.

## Run locally via CLI

```bash
python demo.py
```

(`cli.py` is kept as an identical alias, for anyone who already has muscle memory for it.)

Demo scenarios to try:
```
(intake_agent) >> Need drinking water in Galle
(dedup_dispatch_agent) >> We have 50 food packs available in Colombo
(intake_agent) >> Elderly couple needs medicine urgently in Matara, no transport
(intake_agent) >> What's the status in Galle?
```

The "no transport" scenario is worth trying specifically: there's no medicine offer in Matara
itself, but there is one in Ratnapura from a donor who explicitly can deliver - `match_resources`
should surface it as the top cross-region match, and the final reply should flag the distance
and delivery consideration rather than silently treating it as a local, settled match.

Note the prompt shows whichever agent last responded - after a full pipeline run it will show
`dedup_dispatch_agent` since that's the agent that sent the final reply. Use `!new` to start a
fresh conversation/session, or `!list` to see all registered agents.

## Run as a REST API

```bash
python api.py
```

This starts the API on `http://localhost:8000` (configurable in `config.yaml`).

```bash
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Need drinking water in Galle",
    "session_id": "field-worker-1",
    "agent": "intake_agent"
  }'
```

```bash
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "We have 50 food packs available in Colombo, contact Priya on 0771234567",
    "session_id": "donor-1",
    "agent": "intake_agent"
  }'
```

```bash
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Whats the current status in Galle?",
    "session_id": "coordinator-1",
    "agent": "intake_agent"
  }'
```

Send a second, similar request for the same region/resource shortly after the first to see the
dedup step in action (it should merge quantities into the existing open request instead of
creating a duplicate).

`session_id` scopes the *conversation* (so an agent remembers what it just asked you); it does
**not** scope the disaster-response memory, which is shared across all sessions/regions for the
life of the process, by design.

## Project layout

```
agent.py          - the three agents (intake, priority & matching, dedup & dispatch) + handoffs
tool.py           - dummy data store, urgency/distance/transport scoring, matching, dedup, dispatch tools
demo.py           - local CLI entrypoint (canonical name; same AGENTS as api.py)
cli.py            - identical alias for demo.py
api.py            - REST API entrypoint (same AGENTS as demo.py/cli.py)
config.yaml       - Agent Kernel session/logging/API config
test-config.yaml  - Agent Kernel test harness config (comparison mode)
tests/            - test_tool_layer.py (deterministic) + test_agent_e2e.py (live, needs a key)
SPEC.md           - full agent/tool/memory/testing specification
```

## Limitations

- Region distances (`REGION_DISTANCE_KM` in `tool.py`) are a small, hand-entered table for the
  regions used in this demo, not a live geocoding/routing API.
- Disaster-response state (`_STATE`) is in-process memory - it resets on restart and isn't
  shared across multiple running instances (see "Memory Design" above).
- `VOLUNTEER_DIRECTORY` is dummy seed data, not a real donor/volunteer registry.
- WhatsApp dispatch defaults to simulated/dummy mode; real sends require Meta Cloud API
  credentials and, for cold outbound, a pre-approved message template (see above).

## Future deployment

- Point `_STATE` at Redis/DynamoDB/Cosmos DB (region-keyed) so state survives restarts and scales
  across multiple API instances.
- Replace `VOLUNTEER_DIRECTORY` with a live donor/volunteer registry.
- Replace `REGION_DISTANCE_KM` with a real geocoding/routing API for accurate distances.
- Wire `dispatch_notification` to Agent Kernel's WhatsApp channel for real outbound messages
  (already supported - see "Connecting WhatsApp" above; this is now a configuration step).
- Add auth (`RESTAPI.add_auth_handlers`) before exposing the API publicly.
- Deploy with one of Agent Kernel's Terraform modules (AWS/Azure/GCP, serverless or
  containerized), following the pattern in `agent-kernel/use-cases/waste-sorting-assistant/deploy`
  - same `agent.py`, no code changes needed.
