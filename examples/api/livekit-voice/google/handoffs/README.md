# Agent Kernel Realtime Voice Handoffs (Google ADK)

This example shows one voice conversation moving between several agents with **Google ADK's native agent transfers**, over LiveKit, powered by **Gemini Live**.

The scenario is a team offsite. You tell **Maya**, an enthusiastic planner, what you want. She pitches a plan and hands the turn to **Ben**, a cautious budget controller, who works out the real cost and challenges her. The two answer each other, in their own voices, for a few turns **without you speaking**. Then Maya reports back to you with the agreed plan and asks what you think.

| Agent | Role | Tool | Voice |
|---|---|---|---|
| `planner` (Maya) | Takes your request, pitches the best experience, reports to you | `find_venues` | Aoede |
| `budget` (Ben) | Checks the cost, challenges the plan, pushes back or accepts | `estimate_total` | Charon |

`budget` is a `sub_agent` of `planner`, exactly as you would write it for a text run. ADK lets a sub-agent transfer back to its parent, so the two can pass the turn between them. Only the root agent, `planner`, is registered with Agent Kernel.

It uses the `in_memory` queue transport, so the LiveKit gateway and the agent runner run as threads in a single Python process.

## How a transfer works in realtime mode

Agent Kernel starts one ADK `Runner.run_live()` call with one `LiveRequestQueue`. ADK handles the native `transfer_to_agent` action, calls the new agent's tools, and manages its Gemini Live connection. Agent Kernel reads ADK's event author and changes the speaking LiveKit participant. Each agent's voice is set on its native `Gemini(speech_config=...)` model.

## What you see in the room

Every agent in the graph appears in the room as a participant of its own (`agent-planner`, `agent-budget`), with its own audio track. There is nothing to configure: when the call starts, the conversation tells the LiveKit gateway its whole team, and the other agent joins the room about a second later.

- Only the agent that has the call is heard, in its own voice; the others stay connected and muted (their tiles show a muted mic). On a transfer, the previous agent finishes what it was saying and the next agent's participant takes over, so the room client's speaking indicator moves to it.
- Each agent's words are published to the room chat from its own participant.
- Each agent participant carries an `ak.active` attribute, `"true"` on the one that has the call, for a custom client UI to highlight.
- Only `agent-planner`'s connection listens to you; no agent's audio or chat is ever taken as your input.

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

1. *"Hi, we want to plan a two-night offsite for our team of eight, somewhere in Lisbon."* — Maya looks up venues and pitches the lakeside lodge.
2. Maya transfers to Ben. Ben runs the numbers, says the total out loud and challenges her: drop the boat trips, or pick the city hotel.
3. Maya answers him and revises. Ben checks the new total and pushes back once more or accepts. You listen to them without speaking.
4. After a few turns Maya turns to you: the agreed plan, the total, where they still disagree, and a question for you.
5. *"I'd rather keep the lodge."* — Maya and Ben continue from there.

The agents are told to stop after three turns each. This is an instruction in their prompts, not a limit enforced by Agent Kernel or ADK, so a model can still keep going. Say something to cut in: your speech interrupts whoever is talking.

## Limits

- **One LiveKit connection per agent.** Every listed agent is a participant for the whole call, so LiveKit bills connection minutes for each.
- **Native live workflows.** Speaking workflow nodes use `mode='chat'` or `mode='task'`. ADK live mode does not support `ParallelAgent` or `LoopAgent`.
- **Native tools only.** ADK runs tools declared on each `LlmAgent`. A tool requesting human confirmation fails because this LiveKit edge has no decision path.
- **One agent speaks at a time.** The conversation between the agents is a series of transfers. They do not listen to each other in parallel, and each one sees the earlier turns through ADK's session history.
- **No enforced turn limit.** Keep a debate short through the prompts, as this example does.
- **Transfers and recovery.** ADK owns Gemini connection changes. Agent Kernel does not replay a transcript. On `google-adk` 2.7 or later, a transfer refused by a `before_tool_callback` keeps the call open.
