# Agent Kernel Realtime Voice Handoffs (OpenAI)

This example shows one voice conversation moving between several agents with the **OpenAI Agents SDK's native handoffs**, over LiveKit, powered by the **OpenAI Realtime API**.

The scenario is the support line of an internet provider:

| Agent | Handles | Tools | Hands off to |
|---|---|---|---|
| `supervisor` | Greeting, general questions, routing | — | `billing`, `tech_support` |
| `billing` | Invoices, charges, payments, refunds | `get_latest_invoice` | `supervisor` |
| `tech_support` | Connection problems, outages, technician visits | `check_outage`, `book_technician` | `supervisor` |

The agents are native `agents.realtime.RealtimeAgent` objects with `handoffs=[...]`, exactly as you would write them for a text run. Only the entry agent, `supervisor`, is registered with Agent Kernel; the specialists are reached through its handoffs.

It uses the `in_memory` queue transport, so the LiveKit gateway and the agent runner run as threads in a single Python process.

## How a handoff works in realtime mode

One OpenAI `RealtimeSession` serves the conversation. The SDK executes each handoff, switches the active agent, and runs that agent's native tools. Agent Kernel changes the speaking LiveKit participant when the SDK reports a handoff.

Every handoff reaches the LiveKit gateway as an `agent_changed` event, in order with the audio around it.

## What you see in the room

Every agent in the graph appears in the room as a participant of its own (`agent-supervisor`, `agent-billing`, `agent-tech_support`), with its own audio track. There is nothing to configure: when the call starts, the conversation tells the LiveKit gateway its whole team, and the specialists join the room about a second later.

- Only the agent that has the call is heard, the others stay connected and muted (their tiles show a muted mic). On a handoff, the previous agent finishes what it was saying and the next agent's participant takes over, so the room client's speaking indicator moves to it.
- Each agent's words are published to the room chat from its own participant.
- Each agent participant carries an `ak.active` attribute, `"true"` on the one that has the call, for a custom client UI to highlight.
- Only `agent-supervisor`'s connection listens to you; no agent's audio or chat is ever taken as your input.

Each agent participant needs a token of its own, so the gateway needs `AK_LIVEKIT__API_KEY` and `AK_LIVEKIT__API_SECRET` (not a single pre-made token). A single agent with no handoffs is one participant, as before.

## Quickstart

### 1. Build and setup
```bash
./build.sh

export OPENAI_API_KEY="sk-..."
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

1. *"Hi, my account number is A-1042. Why is my bill higher this month?"* — the supervisor hands you to **billing**, which looks up the invoice without asking for your account number again.
2. *"And my internet keeps dropping. My postcode is SW1A 1AA."* — billing hands you back to the **supervisor**, which hands you to **tech_support**.
3. *"Can someone come out on Friday?"* — tech_support books a technician.

You can talk over an agent at any time, including while a handoff is happening.

## Limits

- **One model and one voice.** `OpenAIModule.run_options()` sets both on the starting agent. The same live session serves every speaker.
- **One LiveKit connection per agent.** Every listed agent is a participant for the whole call, so LiveKit bills connection minutes for each.
- **Native tools only.** The SDK runs tools declared on each `RealtimeAgent`. Tools needing human approval also fail because this LiveKit edge has no approval path.
- **SDK behavior.** Handoff and guardrail details follow the installed OpenAI Agents SDK; Agent Kernel does not implement another tool or handoff engine.
