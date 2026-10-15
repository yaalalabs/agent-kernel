# Agent Kernel Realtime Voice Handoffs (Google ADK)

This example shows one voice conversation moving between several agents with **Google ADK's native agent transfers**, over LiveKit, powered by **Gemini Live**.

The scenario is the support line of an internet provider:

| Agent | Handles | Tools | Voice |
|---|---|---|---|
| `supervisor` | Greeting, general questions, account check, routing | `verify_account` | Aoede |
| `billing` | Invoices, charges, payments, refunds | `get_latest_invoice` | Charon |
| `tech_support` | Connection problems, outages, technician visits | `check_outage`, `book_technician` | Puck |

`billing` and `tech_support` are `sub_agents` of `supervisor`, exactly as you would write them for a text run. ADK's rules decide who can transfer to whom: the supervisor to its sub-agents, and each specialist back to its parent or across to its peer (unless `disallow_transfer_to_parent` / `disallow_transfer_to_peers` is set). Only the root agent, `supervisor`, is registered with Agent Kernel.

It uses the `in_memory` queue transport, so the LiveKit gateway and the agent runner run as threads in a single Python process.

## How a transfer works in realtime mode

An agent that can transfer is given ADK's own `transfer_to_agent` tool and ADK's transfer instructions. When the model calls it, the tool runs exactly as it does on an ADK run. Any of your own tools can also trigger a transfer by setting `tool_context.actions.transfer_to_agent`, as ADK allows.

A Gemini Live session's instructions and tools are fixed when it opens. So, as ADK's own live runner does, Agent Kernel then closes the socket and opens a new one configured for the new agent, with its instructions, tools and voice. The new socket is seeded with the conversation so far as text, so the new agent knows what the caller already said and answers the question that triggered the transfer.

Every transfer is logged (`Transferring from 'supervisor' to 'billing'`) and reaches the LiveKit gateway as an `agent_changed` event, in order with the audio around it. The new agent sees each earlier turn with who said it (`[supervisor] said: ...`), as ADK presents another agent's turns, so it can tell a teammate's words from its own.

## Refusing a handoff

Realtime calls run an agent's ADK tool callbacks around every tool call, `transfer_to_agent` included, as an ADK run does. The supervisor's `before_tool_callback`, `require_account`, refuses a transfer to `billing` or `tech_support` until the caller's account is verified with `verify_account`: it returns a result in the tool's place, so the transfer does not happen, the supervisor keeps the call, and the model hears why. `verify_account` keeps the account in the ADK tool state, which lasts for the whole call, across transfers.

## Background updates

`book_technician` answers at once and starts a background job: the dispatch system confirms the visit a few seconds later. The job reports back with `RealtimeCall(session_id).post_when_idle(...)`, which waits for a quiet moment (nobody speaking, nothing still owed an answer) before the agent says it, so the update never cuts the caller or the agent off. Whichever agent has the call by then says it.

## Call log

`CallLog`, a `RealtimeHook` attached with `realtime_hook(supervisor, [...])`, logs what the caller and each agent said and who has the call (`[call room_01] caller: ...`, `[call room_01] billing: ...`). It sees the specialists' turns too: hooks attach to the agent a call starts with. An application would store or show these instead of logging them.

## What you see in the room

Every agent in the graph appears in the room as a participant of its own (`agent-supervisor`, `agent-billing`, `agent-tech_support`), with its own audio track. There is nothing to configure: when the call starts, the conversation tells the LiveKit gateway its whole team, and the specialists join the room about a second later.

- Only the agent that has the call is heard, in its own voice; the others stay connected and muted (their tiles show a muted mic). On a transfer, the previous agent finishes what it was saying and the next agent's participant takes over, so the room client's speaking indicator moves to it.
- Each agent's words are published to the room chat from its own participant.
- Each agent participant carries an `ak.active` attribute, `"true"` on the one that has the call, for a custom client UI to highlight.
- Only `agent-supervisor`'s connection listens to you; no agent's audio or chat is ever taken as your input.

Each agent participant needs a token of its own, so the gateway needs `AK_LIVEKIT__API_KEY` and `AK_LIVEKIT__API_SECRET` (not a single pre-made token). A single agent with no handoffs is one participant, as before.

## Quickstart

### 1. Build and setup
```bash
./build.sh

export GEMINI_API_KEY="..."
export AK_LIVEKIT__URL="wss://your-project.livekit.cloud"
export AK_LIVEKIT__API_KEY="..."
export AK_LIVEKIT__API_SECRET="..."
```

### 2. Run the server
```bash
uv run server.py
```

Connect to `room_01` in your LiveKit Sandbox dashboard and speak.

### 3. Try a conversation

1. *"Hi, why is my bill higher this month?"* — the supervisor asks for your account number first: a transfer before it is refused (`require_account`).
2. *"It's A-1042."* — the supervisor verifies it and transfers you to **billing** (a new voice), which looks up the invoice without asking for your account number again.
3. *"And my internet keeps dropping. My postcode is SW1A 1AA."* — billing transfers you to **tech_support**.
4. *"Can someone come out on Friday?"* — tech_support requests a technician; a few seconds later, at a quiet moment, it tells you the dispatch system confirmed the visit.

The log shows the call as it goes (`CallLog`).

## Tests

```bash
uv run pytest
```

The tests need no model, LiveKit server or key: they check the handoff rule, the background confirmation and the call log.

## Limits

- **A short gap on every transfer.** Opening the new socket takes about a second or two. What the caller says meanwhile is held (its latest 5 seconds) and passed to the new agent.
- **One LiveKit connection per agent.** Every agent in the graph is a participant for the whole call, so LiveKit bills connection minutes for each.
- **LLM agents only.** Every agent the conversation can transfer to must be an `LlmAgent` with a Gemini Live model and a string `instruction`; a workflow agent (e.g. `SequentialAgent`) or an instruction provider is rejected when the call connects.
- **One transfer per model turn.** If the model asks for two transfers in one turn, the first is performed and the second is answered as not performed. Any other tool called in the same turn runs, and its result reaches the new agent, as on an ADK run.
- **Function tools only.** As for a single realtime agent, toolsets (e.g. MCP) are not offered.
