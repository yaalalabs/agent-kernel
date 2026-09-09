# Disaster Response & Resource Coordination Agent Specification

## Problem

During floods and other disasters in Sri Lanka, needs ("we need drinking water in Galle") and
offers ("we have 50 food packs available in Colombo") arrive as free-form messages from field
workers, volunteers, and community groups across many uncoordinated channels. Nobody has a
single live picture of what's needed where, what's available where, which requests are the
most urgent, or which needs and offers should actually be paired up and dispatched to each
other - and duplicate reports of the same ongoing need routinely get logged as separate items.
This wastes scarce volunteer time and delays help reaching the people who need it most.

## Agent Description

Three Agent Kernel agents (OpenAI Agents SDK), chained by handoffs so a single incoming
message flows through the full pipeline in one turn:

```
intake_agent  --handoff-->  priority_matching_agent  --handoff-->  dedup_dispatch_agent
```

| Agent | Responsibility |
|---|---|
| `intake_agent` | Parses a free-form message into structured fields (need/offer, resource type, quantity, unit, region, contact), or answers a region status/tracking question directly. |
| `priority_matching_agent` | Scores urgency for needs (resource criticality + vulnerable-group indicators + quantity), then finds candidate matches across ALL regions, ranked by quantity coverage, proximity/distance, and transport compatibility. |
| `dedup_dispatch_agent` | Checks memory for an existing open record of the same need/offer in the same region, merges into it or creates a new one, and dispatches a WhatsApp notification to the best match. |

## Tool Responsibilities

All tools live in `tool.py` and are deterministic (no LLM judgement inside a tool) - the agents
decide *when* to call a tool and *what to say* about the result, but the actual scoring/matching
logic is plain Python so it's consistent and testable independent of the model.

| Tool | Used by | Does |
|---|---|---|
| `submit_intake` | intake_agent | Records a structured intake; canonicalizes resource_type through a synonym table ("food"/"food packs"/"meals" all become the same category, so a matching gap doesn't silently hide real matches); detects a transport/logistics signal ("no transport", "can deliver") from the raw message text. |
| `get_region_status` | intake_agent | Returns all open requests/offers for a region, for tracking questions. |
| `score_urgency` | priority_matching_agent | Combines resource criticality, quantity, and detected vulnerable-group keywords into a 0-100 urgency score and band. |
| `match_resources` | priority_matching_agent | Searches the opposite pool (offers for a need, needs for an offer) across all regions; scores each candidate on quantity coverage, proximity (approximate road distance), and transport compatibility. |
| `check_pending_duplicates` | dedup_dispatch_agent | Looks for an existing open record of the same resource_type in the same region. |
| `finalize_record` | dedup_dispatch_agent | Creates a new record, or merges into a duplicate (summing quantity, taking the higher urgency score, adopting a positive transport signal). |
| `dispatch_notification` | dedup_dispatch_agent | Simulates (or, if configured, sends a real) WhatsApp notification to the matched party; flags cross-region matches with the approximate distance so a coordinator knows to confirm delivery logistics. |

## Functional Requirements

- Build three Agent Kernel agents chained by handoffs as above.
- Extract message_type, resource_type, quantity, unit, and region from free-form text; ask at
  most one clarifying question, and only if the region is missing entirely.
- Score urgency for needs using resource criticality, vulnerable-group indicators (children,
  elderly, pregnant, disabled, medical), and quantity - never let the model invent a score.
- Match needs against offers (and vice versa) across all tracked regions, not just the
  requester's own region, weighing quantity coverage, distance, and transport compatibility.
- Detect duplicate open requests/offers in the same region before creating a new record, and
  merge into the existing one instead.
- Simulate (dummy mode) or send (real mode) a WhatsApp notification to the matched party, and
  explicitly flag cross-region matches with the approximate distance.
- Answer direct region status/tracking questions without going through the full intake pipeline.

## Memory Requirements

- Session memory (Agent Kernel's built-in, per-conversation) is used for normal chat context
  within one CLI/API session - `config.yaml` currently sets `session.type: in_memory`.
- Disaster-response state itself (open requests/offers, region by region) is intentionally
  **process-global**, not session-scoped (`tool.py`'s `_STATE` dict) - a disaster spans many
  users/sessions over days, so this memory needs to be shared across every session, not private
  to one conversation.
- Current implementation: in-process Python dict (`_STATE`), which is fine for a local demo but
  is lost when the process restarts and can't be shared across multiple running instances.
- Production-ready path (not yet wired up, but the architecture is ready for it): swap `_STATE`
  for Agent Kernel's Redis/DynamoDB/CosmosDB-backed session storage (see
  `agent-kernel/examples/memory`), keyed by region instead of by session id, so the same shared
  "disaster state" survives restarts and is visible to every process/instance handling traffic
  for that disaster.

## Agent Kernel Requirements

- Built on the OpenAI Agents SDK integration (`agentkernel.openai`), using Agent Kernel's
  handoff mechanism to chain the three agents.
- LLM calls go through Gemini via LiteLLM's native Gemini integration (`gemini/<model>` with
  `GEMINI_API_KEY`) rather than Gemini's OpenAI-compatible endpoint - see `agent.py` and
  `README.md` for why.
- Tools are bound with `OpenAIToolBuilder.bind(...)`.
- Local CLI entry point (`demo.py` / `cli.py`) uses `agentkernel.cli.CLI`.
- REST API entry point (`api.py`) uses `agentkernel.api.RESTAPI`.

## Local Execution

- Requires Python 3.12+ and `uv`.
- `./build.sh` (or on Windows, `uv venv --allow-existing` + `uv sync --all-extras` directly).
- `GEMINI_API_KEY` is required; `agent.py` raises a clear error at startup if it's missing.
- `uv run python demo.py` for the interactive CLI, or `uv run python api.py` for the REST API.
- See `README.md` for full setup, Windows-specific notes, and example requests.

## Testing

- `tests/test_tool_layer.py` - deterministic, LLM-free unit tests covering intake extraction,
  urgency scoring, resource matching (including distance/transport), duplicate detection, merge
  behavior, and dispatch/notification behavior. Run with `uv run pytest tests/test_tool_layer.py`.
- `tests/test_agent_e2e.py` - an end-to-end conversational test that drives the real agents
  (via Agent Kernel's built-in test harness, `agentkernel.test.Test`) through the full pipeline.
  Requires a live `GEMINI_API_KEY` and is skipped automatically if one isn't set.
- `test-config.yaml` configures the test harness comparison mode (`fuzzy`).

## Expected Workflow

1. A field worker/volunteer sends a free-form message (CLI, REST API, or eventually
   WhatsApp/Slack).
2. `intake_agent` extracts the structured fields and calls `submit_intake`, then hands off.
3. `priority_matching_agent` scores urgency (needs only) and calls `match_resources`, which
   searches across all regions and ranks candidates by coverage/distance/transport, then hands
   off.
4. `dedup_dispatch_agent` checks for duplicates, creates or merges the record, dispatches a
   notification to the best match if one is strong enough, and replies to the user with a short
   confirmation - including an explicit flag if the match crosses regions.
5. A coordinator can ask "What's the status in Galle?" at any time to see all open
   requests/offers for a region directly, without going through the full pipeline.

## Deployment

- Not yet deployed; this is a local/demo-stage project for the mini-competition.
- The architecture keeps agent/tool logic independent of the entry point (`demo.py`/`cli.py`
  and `api.py` both just register the same `AGENTS`), so it's ready to be wired into an AWS
  Lambda or Azure Function entry point later, following the pattern in
  `agent-kernel/use-cases/waste-sorting-assistant/deploy` and `agent-kernel/examples/api`.
- WhatsApp integration already exists in `tool.py` (`dispatch_notification`) behind a
  `WHATSAPP_ENABLED` flag; going from dummy to real mode is a configuration change, not a code
  change (see README.md).

## Limitations

- Region distances (`REGION_DISTANCE_KM` in `tool.py`) are a small, hand-entered table for the
  regions used in this demo, not a live geocoding/routing API.
- Disaster-response state (`_STATE`) is in-process memory - it resets on restart and isn't
  shared across multiple running instances (see "Memory Requirements" above).
- `VOLUNTEER_DIRECTORY` is dummy seed data, not a real donor/volunteer registry.
- WhatsApp dispatch defaults to simulated/dummy mode; real sends require Meta Cloud API
  credentials and, for cold outbound, a pre-approved message template (see README.md).
