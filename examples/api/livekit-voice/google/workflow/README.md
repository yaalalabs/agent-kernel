# Agent Kernel Realtime Voice Workflow (Google ADK)

This example shows one voice conversation that follows **a fixed order of steps**, written as a **Google ADK `Workflow`**, over LiveKit, powered by **Gemini Live**.

The scenario is a clinic booking line. The caller always goes through three steps, in this order:

| Step | Agent | Job | Tool | Voice |
|---|---|---|---|---|
| 1 | `intake` (Ana) | Greets the caller, asks the name and the reason for the visit | none | Aoede |
| 2 | `scheduler` (Ben) | Asks the day, reads the free slots, lets the caller pick one | `find_slots` | Charon |
| 3 | `confirmer` (Kim) | Books the appointment, reads the reference, says goodbye | `book_appointment` | Kore |

## Workflow or sub-agents?

The [handoffs example](../handoffs/README.md) uses `sub_agents`: the model decides when to transfer and to whom. Here the **developer** fixes the order with edges, and the model only decides when its own step is done.

```python
booking_flow = Workflow(
    name="booking_flow",
    edges=[("START", intake), (intake, scheduler), (scheduler, confirmer)],
)
```

Each speaking node declares `mode="task"`. A task node talks to the caller until it has what it needs, then calls ADK's own `finish_task` tool, and the next edge starts the next node. A node left without a mode runs outside the live connection, and ADK raises no error, so the caller would hear nothing from it. Always set the mode.

The workflow itself is a container and does not speak. Only the workflow is registered with Agent Kernel. It uses the `in_memory` queue transport, so the LiveKit edge and the agent runner run as threads in a single Python process.

## What you see in the room

When the call starts, the room shows `agent-intake`, `agent-scheduler` and `agent-confirmer` as participants of their own. The workflow does not speak, so the room hears about each node when ADK first names it as the speaker. Only the node that has the call is heard; the others stay muted.

Each agent participant needs a token of its own, so the edge needs `AK_LIVEKIT__API_KEY` and `AK_LIVEKIT__API_SECRET`.

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

Point LiveKit's webhook at the server (see the parent README), then join a room, for example `call_01`, in your LiveKit Sandbox dashboard and speak. Each room is its own call.

### 3. Try a conversation

1. Ana greets you. *"Hi, I'd like to see someone about a sore knee. My name is Sam."*
2. Ana has both, so she finishes her step. Ben takes over and asks which day suits you.
3. *"Tomorrow."* Ben reads the free slots. *"The eleven o'clock one."*
4. Kim books it, reads you the reference and says goodbye.

## Limits

- **One path only.** ADK cannot feed two live nodes from one queue at once, so keep the live nodes in a single line. ADK does not support `ParallelAgent` or `LoopAgent` in live mode.
- **Each speaking node needs `mode="task"` or `mode="chat"`.** Without one the node does not run on the live connection.
- **One agent speaks at a time.** Each step is a separate Gemini Live connection; ADK opens it, and the caller hears a short gap between steps.
- **Tools run in ADK.** Agent Kernel system tools attach to each speaking node when enabled, by the node's own name. A tool that requires confirmation fails the connection, because a realtime session has no decision path.
- **No enforced turn limit.** A step ends when the model calls `finish_task`. If a model never does, that step goes on.
