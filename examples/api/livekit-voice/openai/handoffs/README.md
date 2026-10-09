# Agent Kernel Realtime Voice Handoffs (OpenAI)

This example shows one voice conversation moving between several agents with the **OpenAI Agents SDK's native handoffs**, over LiveKit, powered by the **OpenAI Realtime API**.

The scenario is the support line of an internet provider:

| Agent | Handles | Tools | Hands off to |
|---|---|---|---|
| `supervisor` | Greeting, general questions, routing | — | `billing`, `tech_support` |
| `billing` | Invoices, charges, payments, refunds | `get_latest_invoice` | `supervisor` |
| `tech_support` | Connection problems, outages, technician visits | `check_outage`, `book_technician` | `supervisor` |

The agents are ordinary `agents.Agent` objects with `handoffs=[...]`, exactly as you would write them for a text run. Only the entry agent, `supervisor`, is registered with Agent Kernel; the specialists are reached through its handoffs.

It uses the `in_memory` queue transport, so the LiveKit gateway and the agent runner run as threads in a single Python process.

## How a handoff works in realtime mode

One OpenAI Realtime socket serves the whole conversation. Each agent's handoffs are offered to the model as functions (`transfer_to_billing`, ...). When the model calls one, Agent Kernel invokes the handoff through the SDK, points the session at the new agent's instructions and tools, and the new agent answers. The conversation stays on OpenAI's side, so the new agent already knows everything the caller said.

Every handoff is logged (`Handed off from 'supervisor' to 'billing'`) and reaches the LiveKit gateway as an `agent_changed` event, in order with the audio around it.

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
python server.py
```

Connect to `room_01` in your LiveKit Sandbox dashboard and speak.

### 3. Try a conversation

1. *"Hi, my account number is A-1042. Why is my bill higher this month?"* — the supervisor hands you to **billing**, which looks up the invoice without asking for your account number again.
2. *"And my internet keeps dropping. My postcode is SW1A 1AA."* — billing hands you back to the **supervisor**, which hands you to **tech_support**.
3. *"Can someone come out on Friday?"* — tech_support books a technician.

You can talk over an agent at any time, including while a handoff is happening.

## Limits

- **One model and one voice.** The socket's model and voice cannot change once the conversation starts, so every agent speaks with the entry agent's model and voice, each through its own participant. A specialist declaring a different `model` logs a warning.
- **One LiveKit connection per agent.** Every agent in the graph is a participant for the whole call, so LiveKit bills connection minutes for each.
- **History filters cannot be applied.** The history lives on OpenAI's side of the socket, so a handoff anywhere in the agent graph with an `input_filter` or `nest_handoff_history` is rejected with a clear error when the call connects.
- **One handoff per model turn.** If the model calls two handoffs in one turn, the first is performed and the second is answered as not performed.
- **Function tools only.** As for a single realtime agent, hosted tools and tools that need approval or carry tool guardrails are not offered.
