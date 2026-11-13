# LiveKit Voice Integration

LiveKit is a realtime voice integration for OpenAI Agents SDK and Google ADK agents. The `LiveKitEdgeAdapter` joins a LiveKit room, sends the user's audio and chat text to the agent, and plays the model's streamed audio and transcript back to the room through Agent Kernel's realtime execution pipeline.

## Overview

The edge runs in `realtime` execution mode. It works on every queue transport:

- **`in_memory` (single process)**: the edges, the Agent Runner and the Response Handler run in one process. This is the simplest setup and the recommended first run.
- **A broker (`kafka`, `nats`, `sqs`)**: the edge (IOHandler process) and the Agent Runner run as two processes that share the queues.

Only OpenAI Agents SDK and Google ADK agents can run in realtime mode. They are the only adapters with a realtime runner (`OpenAIRealtimeRunner`, `GoogleADKRealtimeRunner`). Use a native `RealtimeAgent` for OpenAI, or a live ADK `LlmAgent` for Gemini.

## How It Works

1. A user joins the LiveKit room and starts speaking.
2. The `LiveKitEdgeAdapter` batches the microphone audio (see `input_batch_ms`) and puts it on the input queue. Chat text from the room's data channel goes the same way.
3. The Agent Runner hands each chunk to the `RealtimeConnectionPool`, which keeps one native SDK live session per AK session.
4. The model's audio and transcript are paced at playback speed and put on the output queue.
5. The Response Handler passes each chunk to the edge, which plays the audio into the room and publishes the transcript as a chat message when the turn ends.

For the architecture behind these steps, including multi-agent handoffs, see [Realtime Voice Internals](../architecture/realtime-internals.md).

## Features

- **Realtime voice**: two-way streaming audio between the room and the model.
- **Barge-in**: when the user talks over the model, the model's response is cancelled and the edge clears the audio it has buffered.
- **Caller transcript**: each finished line of the caller reaches the edge as an `InputTranscript` event. The edge does not show it; a `LiveKitEdgeAdapter` subclass can, in `deliver_chunk`.
- **Tools**: the tools declared on the native agent run through the OpenAI Agents SDK or Google ADK, with the Agent Kernel context and system tools available as in other modes.
- **Multi-agent handoffs**: a supervisor hands the call to a specialist and back with the framework's own handoffs, and every agent appears in the room as its own participant. See [Multi-agent handoffs](#multi-agent-handoffs).

## Configuration Steps

### 1. LiveKit Cloud Setup

1. Create a free account at [LiveKit Cloud](https://cloud.livekit.io/).
2. Create a new project.
3. Obtain your server URL, API key, and API secret from the project settings.

### 2. Required Environment Variables

```bash
export AK_LIVEKIT__URL="wss://<your-project>.livekit.cloud"
export AK_LIVEKIT__API_KEY="your_api_key"
export AK_LIVEKIT__API_SECRET="your_api_secret"
```

## Implementation

Like every Agent Kernel integration, each conversation gets its own session. For LiveKit, a conversation is a room: Agent Kernel starts an edge for each room from LiveKit's own room webhooks, as it hosts a Slack webhook, and the room name is the AK session id. It runs in `realtime` mode on every queue transport.

```yaml
# config.yaml
execution:
  mode: realtime
```

### Migrating from v0.9.5

v0.9.5 hosted one fixed room named at start-up. That API is removed, with no alias:

- `IOHandler.run(gateways=[...])` is gone: mount a handler with `handlers=[...]`.
- `GatewayRunner` is no longer exported.
- `LiveKitEdgeGateway` is now `LiveKitEdgeAdapter`, built for you per room.

```python
# before (v0.9.5)
IOHandler.run(gateways=[GatewayRunner(LiveKitEdgeGateway(session_id="room_01"))])

# after
IOHandler.run(handlers=[EdgeLifecycleRESTRequestHandler(LiveKitLifecycleAdapter())])
```

Then point your LiveKit project's webhook at `/livekit/webhook` (see below). Every room now gets its own edge and session, and the first agent comes from `livekit.agent`.

### Hosting the edges

Mount `EdgeLifecycleRESTRequestHandler` with `LiveKitLifecycleAdapter`. It is the same shape as a messaging integration: `LiveKitLifecycleAdapter` only translates LiveKit's own signed room webhooks, and `EdgeLifecycleRESTRequestHandler` hosts it, as `WebhookRESTRequestHandler` hosts the Slack adapter. Agent Kernel hosts the edges; you choose which rooms get one.

- `room_started` starts an edge for the room. The room name is the session id.
- A caller's `participant_joined` also starts one if the edge is not running, so a caller who rejoins after it ended gets a new edge. A caller who rejoins while the old edge is still leaving gets a new edge as soon as it has left. The edge's own `agent-*` participants never start one.
- When the last caller leaves, that edge ends the session at once and leaves the room.
- `room_finished` stops the room's edge if it is still running.

```python
from agents.realtime import RealtimeAgent

from agentkernel.framework.openai import OpenAIModule
from agentkernel.integration.adapter import EdgeLifecycleRESTRequestHandler
from agentkernel.integration.livekit import LiveKitLifecycleAdapter
from agentkernel.pipeline import IOHandler

agent = RealtimeAgent(
    name="voice_assistant",
    instructions="You are a helpful voice assistant.",
)
OpenAIModule([agent]).run_options(agent, model_config={"initial_model_settings": {"model_name": "gpt-realtime", "voice": "alloy"}})


class CallRooms(LiveKitLifecycleAdapter):
    def should_start(self, session_id: str) -> bool:
        return session_id.startswith("call_")


if __name__ == "__main__":
    IOHandler.run(handlers=[EdgeLifecycleRESTRequestHandler(CallRooms())])
```

In LiveKit Cloud, add a webhook (**Settings → Webhooks**) that calls `https://<your-host>/livekit/webhook`. On a laptop, expose the port with a tunnel (for example ngrok) first. LiveKit signs the webhook with your API key; `LiveKitLifecycleAdapter` checks the signature with `AK_LIVEKIT__API_KEY` and `AK_LIVEKIT__API_SECRET` (or the keys you pass it) and answers 401 to anything else. There is no new configuration. Override `should_start(session_id)` to choose the rooms (every room by default), and `create_edge(session_id)` to build the edge yourself. Webhook retries are safe: a room that already has an edge is left alone. When the process shuts down, it starts no new edge and the live calls are closed with it.

### Two processes (broker transport)

With `execution.queues.type` set to `kafka`, `nats` or `sqs`, start the same module in two roles: the IOHandler, which serves the webhook and hosts the edges, and the Agent Runner.

```python
from agentkernel.integration.adapter import EdgeLifecycleRESTRequestHandler
from agentkernel.integration.livekit import LiveKitLifecycleAdapter
from agentkernel.pipeline import AgentRunner, IOHandler

# Process 1: the edges and the Response Handler
IOHandler.run(handlers=[EdgeLifecycleRESTRequestHandler(LiveKitLifecycleAdapter())])

# Process 2: the Agent Runner, which holds native live sessions
AgentRunner.run()
```

Run the Agent Runner as a single replica: its connection pool is local to the process. Run one IOHandler process that hosts the edge for every room, because replies are routed to the edge registered in that process.

:::note Execution Mode
LiveKit requires the Agent Kernel execution mode to be set to `realtime`. Standard async/sync text modes will not work. Ensure you have `execution.mode: realtime` set in your `config.yaml`.
:::

### Realtime pacing and audio batching

Two `execution.realtime` knobs tune the audio pipeline:

- `playback_lead_ms` (default `50`): outbound model audio is paced so the edge holds this much
  audio ahead of playback. Low-latency transports (in-process, Kafka, NATS) are fine at the
  default; a store-and-forward broker such as SQS adds latency and jitter per chunk, so raise it
  to keep playback from underrunning (heard as choppy or missing audio).
- `input_batch_ms` (default `100`): inbound mic audio is accumulated to this many milliseconds per
  input-queue message. Batching keeps message count, broker cost, and per-message overhead low.
  Set it to `0` to pass every frame straight through for the lowest input latency (many more
  messages, so only sensible on a low-cost transport).

```yaml
execution:
  mode: realtime
  realtime:
    playback_lead_ms: 250
    input_batch_ms: 100
```

Both are settable from the environment too (`AK_EXECUTION__REALTIME__PLAYBACK_LEAD_MS`,
`AK_EXECUTION__REALTIME__INPUT_BATCH_MS`). A larger playback lead is smoother but adds a little
latency at the start of each response.

### Tools and framework context

Declare realtime tools on the native `RealtimeAgent` or ADK `LlmAgent`. The SDK calls them and returns their results. Inside a tool, `ToolContext.get()`, `Session.current()` and `Agent.current()` work as they do in other execution modes: the pool sets them once when the call opens, and the SDK's own tasks inherit them. The session lock is not held while a tool runs, because a call is one long-lived session. Agent Kernel system tools (multimodal, sandbox, schedule, knowledge base) and their prompt guidance are attached as in other modes. An ADK `Workflow` root holds no tools of its own, so they attach to its speaking agents, each looked up by its own name for the `agents` allow-lists. A realtime session does not carry the AK session's `framework_context`: the native tools get no context object (use `ToolContext` to reach the AK session). The AK session is stored once, when a call ends normally, as `Runtime.stream` stores a stream that ended normally: with a durable session store (`redis`, `valkey`, `dynamodb`, ...) what the call changed (the session owner, state hooks kept in the non-volatile cache, ADK's conversation) is there for the next load. A call that fails, or a process that dies mid-call, stores nothing. OpenAI keeps its conversation inside its own live session, so on OpenAI only the AK-side state is stored.

A schedule created during a call (`create_schedule`) works and acts as the caller. When it fires, though, it is a chat request with no caller listening, so a realtime deployment is not the place for it to run: it is not recorded as an occurrence there, and it either opens a native session whose output nobody reads or, with `session_mode: reuse` and a live call on the same session, is sent into that call as text. Deliver scheduled occurrences to a text-mode deployment's queue.

## The opening prompt

When a caller joins the room, whether or not their microphone is published yet, the edge asks the conversation to say a short hello. A caller who was already in the room when the edge joined is greeted too. Override `opening_prompt(participant_identity)` to open with words of your own, or return `None` to send nothing. The edge greets each caller once, so a duplicate join event does not send the hello twice; it forgets a caller when they leave, so a rejoin is greeted again.

```python
class SupportEdge(LiveKitEdgeAdapter):
    def opening_prompt(self, participant_identity: str) -> str | None:
        return f"Greet {participant_identity} by name and ask how you can help today."
```

When an edge stops or loses its room it sends an end-of-session control, so the native session closes at once.

## Multi-agent handoffs

One call can move between several agents. Declare native live agents and register the entry agent:

- **OpenAI Agents SDK**: `RealtimeAgent(handoffs=[...])`. The SDK executes each handoff and updates the active agent.
- **Google ADK**: `LlmAgent(sub_agents=[...])`. ADK's own rules decide who can transfer to whom: an agent to its sub-agents, and back to its parent or across to its peers unless `disallow_transfer_to_parent` / `disallow_transfer_to_peers` is set.

```python
from agents.realtime import RealtimeAgent

from agentkernel.framework.openai import OpenAIModule
from agentkernel.integration.adapter import EdgeLifecycleRESTRequestHandler
from agentkernel.integration.livekit import LiveKitLifecycleAdapter
from agentkernel.pipeline import IOHandler

supervisor = RealtimeAgent(name="supervisor", instructions="Route the caller to billing or tech support.")
billing = RealtimeAgent(name="billing", instructions="Answer billing questions.", handoffs=[supervisor])
tech_support = RealtimeAgent(name="tech_support", instructions="Fix connection problems.", handoffs=[supervisor])
supervisor.handoffs = [billing, tech_support]

OpenAIModule([supervisor]).run_options(supervisor, model_config={"initial_model_settings": {"model_name": "gpt-realtime", "voice": "alloy"}})

if __name__ == "__main__":
    IOHandler.run(handlers=[EdgeLifecycleRESTRequestHandler(LiveKitLifecycleAdapter())])
```

With `livekit.agent: supervisor` in `config.yaml`, the supervisor answers every call (the same field Slack has as `slack.agent`). The conversation, and the context the caller has given, carries over to the agent that takes the call.

### What the caller sees in the room

Every agent the entry agent can reach through handoffs appears as a participant of its own (`agent-supervisor`, `agent-billing`, `agent-tech_support`), with its own audio track. There is nothing to configure: when the call starts, the conversation tells the edge its whole team, and the other agents join the room about a second later.

- Only the agent that has the call is heard and unmuted; the others stay connected and muted.
- On a handoff, the previous agent finishes what it was saying before the next agent's participant takes over, so the room client's speaking indicator moves to it.
- Each agent's words are published to the room chat from its own participant.
- Each agent participant carries an `ak.active` attribute, `"true"` on the one that has the call, for a custom client UI to highlight.
- Only the first participant listens to the caller; no agent's audio or chat is ever taken as the caller's input.

Each agent participant needs a token of its own, so the edge needs `AK_LIVEKIT__API_KEY` and `AK_LIVEKIT__API_SECRET` rather than a single pre-made `token`; with only a token, the whole team speaks through one participant (a warning is logged). A single agent with no handoffs is one participant, as before.

### How the two frameworks differ

| | OpenAI Agents SDK | Google ADK |
|---|---|---|
| Live session | One native `RealtimeSession` for the call | One native `Runner.run_live()` and `LiveRequestQueue` for the call |
| Handoff | `RealtimeAgent.handoffs` | ADK agent transfers (`sub_agents`) and live `Workflow` steps |
| Tools | Native tools on each `RealtimeAgent` | Native tools and toolsets on each `LlmAgent` |
| Voice | One session voice through `model_config` | Per-agent `Gemini(speech_config=...)` or session `RunConfig.speech_config` |

For how handoffs flow through the pipeline, see [Realtime Voice Internals](../architecture/realtime-internals.md).

## Example Projects

Complete working examples (with In-Memory, Kafka, NATS, and AWS SQS architectures) are available in the **examples/api/livekit-voice** directory. The `openai/handoffs` variant shows multi-agent handoffs with an internet support line (supervisor, billing and tech support). The `google/handoffs` variant shows two agents passing the turn back and forth with ADK transfers (a planner and a budget controller) before reporting to the caller. The `google/workflow` variant shows a fixed order of steps (intake, scheduler, confirmer) written as an ADK `Workflow`. Every variant hosts the edges with `EdgeLifecycleRESTRequestHandler` and `LiveKitLifecycleAdapter`, one room per call.

## Limitations

- **AK hooks** run on a call: typed text through `on_run`, caller audio through `on_stream_input`, and output events through `on_stream_event` (see [Realtime calls](hooks.md#realtime-hooks)). The input guardrail checks typed text only, so caller audio reaches the model unchecked unless a pre-hook turns it into text. The output guardrail does not run on a streamed reply. Use native SDK live features where supported.
- **Human approval** has no decision path in this LiveKit edge. Approval-requiring OpenAI tools and ADK confirmation requests fail the connection clearly.
- **No session lock around tools.** The SDK runs the tools; AK sets the tool context when the call opens but does not hold the session lock while a tool runs.
- **One room per edge**: each `LiveKitEdgeAdapter` joins one room, and the room uses one AK session. Everyone in the room shares that conversation: the model hears one audio stream and cannot tell speakers apart. Give each caller their own room for a private call.
- **A webhook is required**: LiveKit must reach the IOHandler process. On a laptop, expose it with a tunnel, as for Slack.
- **Connection lifetime**: a failed or expired native session is closed. A later input can start a fresh session; AK does not replay the old transcript.
- **One LiveKit connection per agent**: with handoffs, every listed agent is a participant, and LiveKit bills connection minutes for each.
- **Single replicas**: one Agent Runner replica and one IOHandler process, as described above.
