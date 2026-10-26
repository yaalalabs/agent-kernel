# LiveKit Voice Integration

LiveKit is a realtime voice integration for OpenAI Agents SDK and Google ADK agents. The `LiveKitEdgeGateway` joins a LiveKit room, sends the user's audio and chat text to the agent, and plays the model's streamed audio and transcript back to the room through Agent Kernel's realtime execution pipeline.

## Overview

The gateway runs in `realtime` execution mode. It works on every queue transport:

- **`in_memory` (single process)**: the gateway, the Agent Runner and the Response Handler run in one process. This is the simplest setup and the recommended first run.
- **A broker (`kafka`, `nats`, `sqs`)**: the gateway (IOHandler process) and the Agent Runner run as two processes that share the queues.

Only OpenAI Agents SDK and Google ADK agents can run in realtime mode. They are the only adapters with a realtime runner (`OpenAIRealtimeRunner`, `GoogleADKRealtimeRunner`). Use a native `RealtimeAgent` for OpenAI, or a live ADK `LlmAgent` for Gemini.

## How It Works

1. A user joins the LiveKit room and starts speaking.
2. The `LiveKitEdgeGateway` batches the microphone audio (see `input_batch_ms`) and puts it on the input queue. Chat text from the room's data channel goes the same way.
3. The Agent Runner hands each chunk to the `RealtimeConnectionPool`, which keeps one native SDK live session per AK session.
4. The model's audio and transcript are paced at playback speed and put on the output queue.
5. The Response Handler passes each chunk to the gateway, which plays the audio into the room, writes the transcript as live captions while it plays, and publishes it as a chat message when the turn ends.

For the architecture behind these steps, including multi-agent handoffs, see [Realtime Voice Internals](../architecture/realtime-internals.md).

## Features

- **Realtime voice**: two-way streaming audio between the room and the model.
- **Barge-in**: when the user talks over the model, the model's response is cancelled and the gateway clears the audio it has buffered.
- **Live captions**: the gateway publishes each agent's words, as they are spoken, and the caller's finished lines, on LiveKit's `lk.transcription` text streams, so standard LiveKit client components show them. The turn-end chat message stays.
- **Server hooks**: `on_transcript`, `on_agent_changed` and `on_error` let your own code follow the call. See [Following the call from server code](#following-the-call-from-server-code).
- **Tools**: realtime runs native agent tools only, through the OpenAI Agents SDK or Google ADK.
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

The gateway is hosted with `GatewayRunner` and passed to `IOHandler.run(gateways=...)`. One gateway serves one room, and its `session_id` is the room name.

### Single process (`in_memory`)

```yaml
# config.yaml
execution:
  mode: realtime
```

```python
from agents.realtime import RealtimeAgent as OpenAIAgent

from agentkernel.framework.openai import OpenAIModule
from agentkernel.integration.adapter import GatewayRunner
from agentkernel.integration.livekit import LiveKitEdgeGateway
from agentkernel.pipeline import IOHandler

agent = OpenAIAgent(
    name="voice_assistant",
    instructions="You are a helpful voice assistant.",
)
OpenAIModule([agent]).run_options(agent, model_config={"initial_model_settings": {"model_name": "gpt-realtime", "voice": "alloy"}})

if __name__ == "__main__":
    IOHandler.run(gateways=[GatewayRunner(LiveKitEdgeGateway(session_id="room_01"))])
```

### Two processes (broker transport)

With `execution.queues.type` set to `kafka`, `nats` or `sqs`, start the same module in two roles:
the IOHandler with the gateway, and the Agent Runner.

```python
from agentkernel.integration.adapter import GatewayRunner
from agentkernel.integration.livekit import LiveKitEdgeGateway
from agentkernel.pipeline import AgentRunner, IOHandler

# Process 1: the gateway and the Response Handler
IOHandler.run(gateways=[GatewayRunner(LiveKitEdgeGateway(session_id="room_01"))])

# Process 2: the Agent Runner, which holds native live sessions
AgentRunner.run()
```

Run the Agent Runner as a single replica: its connection pool is local to the process. Run one IOHandler process that hosts the gateway for every room, because replies are routed to the gateway registered in that process.

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

Declare realtime tools on the native `RealtimeAgent` or ADK `LlmAgent`. The SDK calls them and returns their results. OpenAI's native run context can be set through the AK session `framework_context`; that does not create AK `ToolContext`. In realtime mode, AK skips automatic system tools and their prompt guidance; tools you declare on the native agent remain available.

## Following the call from server code

Subclass the gateway and override any of three hooks on `StatefulEdgeAdapter`. Each does nothing by default, so existing gateways are unchanged:

```python
from agentkernel.integration.adapter import TranscriptLine
from agentkernel.integration.livekit import LiveKitEdgeGateway


class LoggingGateway(LiveKitEdgeGateway):
    def on_transcript(self, line: TranscriptLine) -> None:
        # speaker, role ("user" or "agent"), text, at, message_id, interrupted, typed
        print(f"{line.speaker}: {line.text}")

    def on_agent_changed(self, agent: str, previous: str | None) -> None:
        print(f"{previous} -> {agent}")

    def on_error(self, message: str) -> None:
        print(f"error: {message}")
```

- `on_transcript(line)` runs once for each finished agent turn (per speaker, split at handoffs) and once for each caller line. A turn the caller cut off gives the part that was delivered, with `interrupted=True`. The caller's line needs the SDK's input transcription: on by default for ADK, and set through `input_audio_transcription` in the model settings for OpenAI. A message the caller types in the room chat is also a caller line, with `typed=True`, so server code sees typed and spoken input alike. An agent participant's own chat is ignored.
- `on_agent_changed(agent, previous)` runs when the speaking agent changes, in order with the lines.
- `on_error(message)` runs when an error reaches the edge, besides the chat text the room still gets.

Hooks run **in call order on a worker thread of their own** for each gateway, never on the delivery thread that plays the audio, so a slow hook cannot delay anyone's audio. They are plain methods, so they may block (a file write); any state they share with other threads needs its own lock. A hook that raises is logged on `ak.integration.edge_hooks` and ignored.

### The opening prompt

When the caller's microphone appears, the gateway asks the conversation to say a short hello. Override `opening_prompt(participant_identity)` to open with words of your own, or return `None` to send nothing. It is called on every caller track subscription, a rejoin after a page reload included, so keep track of whether you already opened.

```python
class MeetingGateway(LiveKitEdgeGateway):
    def opening_prompt(self, participant_identity: str) -> str | None:
        return f"Open the meeting as the PM: greet {participant_identity} and ask what they want to build."
```

### One gateway per room, started and stopped at runtime

`IOHandler.run(gateways=...)` starts gateways when the app boots. To start one when something happens (a visitor presses *Start a meeting*), use the runner's background start. It returns once the gateway has joined its room, and raises if it could not:

```python
runner = GatewayRunner(LiveKitEdgeGateway(session_id="room-42", agent_name="supervisor"))
runner.start_background()   # raises the edge's own error, or TimeoutError after READY_TIMEOUT_SECONDS (30 s)
...
runner.stop()               # leaves the room and closes the model session at once
```

This needs the single-process `in_memory` topology, with `IOHandler.run(handlers=...)` hosting your routes and no boot-time gateways. A gateway of your own works the same way if it calls `self._mark_ready()` once its platform connection is up. When a gateway stops or loses its room it sends an end-of-session control, so the native session closes at once.

## Multi-agent handoffs

One call can move between several agents. Declare native live agents and register the entry agent:

- **OpenAI Agents SDK**: `RealtimeAgent(handoffs=[...])`. The SDK executes each handoff and updates the active agent.
- **Google ADK**: `LlmAgent(sub_agents=[...])`. ADK's own rules decide who can transfer to whom: an agent to its sub-agents, and back to its parent or across to its peers unless `disallow_transfer_to_parent` / `disallow_transfer_to_peers` is set.

```python
from agents.realtime import RealtimeAgent as OpenAIAgent

from agentkernel.framework.openai import OpenAIModule
from agentkernel.integration.adapter import GatewayRunner
from agentkernel.integration.livekit import LiveKitEdgeGateway
from agentkernel.pipeline import IOHandler

supervisor = OpenAIAgent(name="supervisor", instructions="Route the caller to billing or tech support.")
billing = OpenAIAgent(name="billing", instructions="Answer billing questions.", handoffs=[supervisor])
tech_support = OpenAIAgent(name="tech_support", instructions="Fix connection problems.", handoffs=[supervisor])
supervisor.handoffs = [billing, tech_support]

OpenAIModule([supervisor]).run_options(supervisor, model_config={"initial_model_settings": {"model_name": "gpt-realtime", "voice": "alloy"}})

if __name__ == "__main__":
    IOHandler.run(gateways=[GatewayRunner(LiveKitEdgeGateway(session_id="room_01", agent_name="supervisor"))])
```

The conversation, and the context the caller has given, carries over to the agent that takes the call.

### What the caller sees in the room

Every agent the entry agent can reach through handoffs appears as a participant of its own (`agent-supervisor`, `agent-billing`, `agent-tech_support`), with its own audio track. There is nothing to configure: when the call starts, the conversation tells the gateway its whole team, and the other agents join the room about a second later.

- Only the agent that has the call is heard and unmuted; the others stay connected and muted.
- On a handoff, the previous agent finishes what it was saying before the next agent's participant takes over, so the room client's speaking indicator moves to it.
- Each agent's words are published to the room chat from its own participant, and written as live captions from it.
- Each agent participant carries an `ak.active` attribute, `"true"` on the one that has the call, for a custom client UI to highlight.
- Only the first participant listens to the caller; no agent's audio or chat is ever taken as the caller's input.

Each agent participant needs a token of its own, so the gateway needs `AK_LIVEKIT__API_KEY` and `AK_LIVEKIT__API_SECRET` rather than a single pre-made `token`; with only a token, the whole team speaks through one participant (a warning is logged). A single agent with no handoffs is one participant, as before.

### How the two frameworks differ

| | OpenAI Agents SDK | Google ADK |
|---|---|---|
| Live session | One native `RealtimeSession` for the call | One native `Runner.run_live()` and `LiveRequestQueue` for the call |
| Handoff | `RealtimeAgent.handoffs` | ADK agent transfers and live workflows |
| Tools | Native tools on each `RealtimeAgent` | Native tools and toolsets on each `LlmAgent` |
| Voice | One session voice through `model_config` | Per-agent `Gemini(speech_config=...)` or session `RunConfig.speech_config` |

For how handoffs flow through the pipeline, see [Realtime Voice Internals](../architecture/realtime-internals.md).

## Example Projects

Complete working examples (with In-Memory, Kafka, NATS, and AWS SQS architectures) are available in the **examples/api/livekit-voice** directory. The `openai/handoffs` and `google/handoffs` variants show multi-agent handoffs with an internet support line (supervisor, billing and tech support).

## Limitations

- **AK hooks and guardrails** do not automatically run on native realtime turns. Use native SDK live features where supported.
- **Human approval** has no decision path in this LiveKit edge. Approval-requiring OpenAI tools and ADK confirmation requests fail clearly.
- **Native tools only.** Realtime runs the tools declared on the native agent, through the SDK. AK does not attach its system tools in realtime mode.
- **One room per gateway**: each `LiveKitEdgeGateway` joins one room, and the room uses one AK session. Many gateways can run in one process, each started with `GatewayRunner.start_background()`.
- **Connection lifetime**: a failed or expired native session is closed. A later input can start a fresh session; AK does not replay the old transcript.
- **One LiveKit connection per agent**: with handoffs, every listed agent is a participant, and LiveKit bills connection minutes for each.
- **Single replicas**: one Agent Runner replica and one IOHandler process, as described above.
