# LiveKit Voice Integration

LiveKit is a realtime voice integration for OpenAI Agents SDK and Google ADK agents. The `LiveKitEdgeGateway` joins a LiveKit room, sends the user's audio and chat text to the agent, and plays the model's streamed audio and transcript back to the room through Agent Kernel's realtime execution pipeline.

## Overview

The gateway runs in `realtime` execution mode. It works on every queue transport:

- **`in_memory` (single process)**: the gateway, the Agent Runner and the Response Handler run in one process. This is the simplest setup and the recommended first run.
- **A broker (`kafka`, `nats`, `sqs`)**: the gateway (IOHandler process) and the Agent Runner run as two processes that share the queues.

Only OpenAI Agents SDK and Google ADK agents can run in realtime mode. They are the only adapters with a realtime runner (`OpenAIRealtimeRunner`, `GoogleADKRealtimeRunner`). The agent must name a realtime model, for example `gpt-realtime` or a Gemini Live model.

## How It Works

1. A user joins the LiveKit room and starts speaking.
2. The `LiveKitEdgeGateway` batches the microphone audio (see `input_batch_ms`) and puts it on the input queue. Chat text from the room's data channel goes the same way.
3. The Agent Runner hands each chunk to the `RealtimeConnectionPool`, which keeps one persistent WebSocket per session to the OpenAI Realtime API or Gemini Live.
4. The model's audio and transcript are paced at playback speed and put on the output queue.
5. The Response Handler passes each chunk to the gateway, which plays the audio into the room and publishes the transcript as a chat message when the turn ends.

For the architecture behind these steps, including multi-agent handoffs, see [Realtime Voice Internals](../architecture/realtime-internals.md).

## Features

- **Realtime voice**: two-way streaming audio between the room and the model.
- **Barge-in**: when the user talks over the model, the model's response is cancelled and the gateway clears the audio it has buffered.
- **Tools**: the agent's function tools run during the call, with `ToolContext.get()` available as usual.
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
from agents import Agent as OpenAIAgent

from agentkernel.framework.openai import OpenAIModule
from agentkernel.integration.adapter import GatewayRunner
from agentkernel.livekit import LiveKitEdgeGateway
from agentkernel.pipeline import IOHandler

agent = OpenAIAgent(
    name="voice_assistant",
    model="gpt-realtime",
    instructions="You are a helpful voice assistant.",
)
OpenAIModule([agent])

if __name__ == "__main__":
    IOHandler.run(gateways=[GatewayRunner(LiveKitEdgeGateway(session_id="room_01"))])
```

### Two processes (broker transport)

With `execution.queues.type` set to `kafka`, `nats` or `sqs`, start the same module in two roles:
the IOHandler with the gateway, and the Agent Runner.

```python
from agentkernel.integration.adapter import GatewayRunner
from agentkernel.livekit import LiveKitEdgeGateway
from agentkernel.pipeline import AgentRunner, IOHandler

# Process 1: the gateway and the Response Handler
IOHandler.run(gateways=[GatewayRunner(LiveKitEdgeGateway(session_id="room_01"))])

# Process 2: the Agent Runner, which holds the model sockets
AgentRunner.run()
```

Run the Agent Runner as a single replica: its connection pool is local to the process. Run one IOHandler process that hosts the gateway for every room, because replies are routed to the gateway registered in that process.

:::note Execution Mode
LiveKit requires the Agent Kernel execution mode to be set to `realtime`. Standard async/sync text modes will not work. Ensure you have `execution.mode: realtime` set in your `config.yaml`.
:::

### Tokens for your users

A person joins the room with a token signed by the room's API key and secret. When your app serves a page
for them, ask the gateway for the token: it signs with the settings it already reads, so your code never
reads the LiveKit settings itself.

```python
gateway = LiveKitEdgeGateway(session_id="room_01")

def get_token(name: str) -> dict:
    return {"url": gateway.room_url, "token": gateway.participant_token(f"user-{name}", name)}
```

`participant_token(identity, name=None, **grants)` always joins the gateway's room. The `grants` are LiveKit
`VideoGrants` fields (`can_publish`, `can_subscribe`, `can_publish_data`, ...), with LiveKit's own defaults for
any not given. It raises `ValueError` for an identity starting with `agent-` (the gateway's own agents, see
`LiveKitEdgeGateway.AGENT_IDENTITY_PREFIX`), for `room` or `room_join` in `grants`, and when the gateway has no
`api_key` and `api_secret` (one made with a pre-made `token` only).

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

### Live settings (Google ADK)

How Gemini detects the caller's turns, and which languages it transcribes, come from the ADK
`RunConfig` the call's starting agent declares as a run option, the same option a non-live run
reads. It applies to every socket of the call, the sockets a transfer or a reconnect opens included:

```python
from google.adk.agents.run_config import RunConfig
from google.genai import types

module.run_options(
    supervisor,
    run_config=RunConfig(
        realtime_input_config=types.RealtimeInputConfig(
            automatic_activity_detection=types.AutomaticActivityDetection(
                start_of_speech_sensitivity=types.StartSensitivity.START_SENSITIVITY_LOW,
                silence_duration_ms=800,
            )
        ),
        input_audio_transcription=types.AudioTranscriptionConfig(language_codes=["en-US"]),
    ),
)
```

Agent Kernel reads `realtime_input_config`, `input_audio_transcription` and `output_audio_transcription`;
transcription of both sides stays on when they are unset, since the runner depends on it. A run-options
factory is not called for realtime calls: the call has no per-run requests to give it.

### Tools and framework context

Realtime tool calls receive the session's `framework_context` as their run context, as unary runs
do (`wrapper.context` on OpenAI), and `ToolContext.get()` works as usual. Unlike a unary run, a
realtime tool call does not write `framework_context` back, so changes a tool makes to it are not
persisted.

## Multi-agent handoffs

One call can move between several agents. Write the agents as you would for a text run, and register only the entry agent:

- **OpenAI Agents SDK**: `Agent(handoffs=[...])`. Each agent's handoffs are offered to the model as functions (`transfer_to_billing`, ...).
- **Google ADK**: `LlmAgent(sub_agents=[...])`. ADK's own rules decide who can transfer to whom: an agent to its sub-agents, and back to its parent or across to its peers unless `disallow_transfer_to_parent` / `disallow_transfer_to_peers` is set.

```python
from agents import Agent as OpenAIAgent

from agentkernel.framework.openai import OpenAIModule
from agentkernel.integration.adapter import GatewayRunner
from agentkernel.livekit import LiveKitEdgeGateway
from agentkernel.pipeline import IOHandler

supervisor = OpenAIAgent(name="supervisor", model="gpt-realtime", instructions="Route the caller to billing or tech support.")
billing = OpenAIAgent(name="billing", model="gpt-realtime", instructions="Answer billing questions.", handoffs=[supervisor])
tech_support = OpenAIAgent(name="tech_support", model="gpt-realtime", instructions="Fix connection problems.", handoffs=[supervisor])
supervisor.handoffs = [billing, tech_support]

OpenAIModule([supervisor])

if __name__ == "__main__":
    IOHandler.run(gateways=[GatewayRunner(LiveKitEdgeGateway(session_id="room_01", agent_name="supervisor"))])
```

The conversation, and the context the caller has given, carries over to the agent that takes the call. On Google ADK, the agent that takes the call sees each earlier turn with who said it (`[billing] said: ...`), as ADK presents another agent's turns, so agents can put questions to each other and answer them.

### What the caller sees in the room

Every agent the entry agent can reach through handoffs appears as a participant of its own (`agent-supervisor`, `agent-billing`, `agent-tech_support`), with its own audio track. There is nothing to configure: when the call starts, the conversation tells the gateway its whole team, and the other agents join the room about a second later.

- Only the agent that has the call is heard and unmuted; the others stay connected and muted.
- On a handoff, the previous agent finishes what it was saying before the next agent's participant takes over, so the room client's speaking indicator moves to it.
- Each agent's words are published to the room chat from its own participant.
- Each agent participant carries an `ak.active` attribute, `"true"` on the one that has the call, for a custom client UI to highlight.
- Only the first participant listens to the caller; no agent's audio or chat is ever taken as the caller's input.

Each agent participant needs a token of its own, so the gateway needs `AK_LIVEKIT__API_KEY` and `AK_LIVEKIT__API_SECRET` rather than a single pre-made `token`; with only a token, the whole team speaks through one participant (a warning is logged). A single agent with no handoffs is one participant, as before.

### How the two frameworks differ

| | OpenAI Agents SDK | Google ADK |
|---|---|---|
| Handoff | Same model socket; the session is switched to the new agent's instructions and tools | A new Gemini Live socket for the new agent, seeded with the conversation so far |
| Gap the caller hears | None | About 1 to 2 seconds; what the caller says during it is held (its latest 5 seconds) and sent to the new agent |
| Voice and model | Every agent speaks with the entry agent's model and voice | Each agent its own model and voice (`generate_content_config.speech_config`) |
| Rejected when the call connects | A handoff with `input_filter` or `nest_handoff_history`, which realtime cannot apply | Any reachable agent that is not an `LlmAgent` with a Gemini Live model and a string `instruction` |

For how handoffs flow through the pipeline, see [Realtime Voice Internals](../architecture/realtime-internals.md).

### Refusing a handoff

Agents that can hand off to each other can also do so without the caller, back and forth. Each framework's own hook can refuse a handoff, and the refused agent keeps the call:

- **OpenAI Agents SDK**: wrap the target in `handoff(agent, on_handoff=...)` and raise from the hook. The model gets the exception's message as the handoff's result.
- **Google ADK**: give the agent a `before_tool_callback` that returns a result for `transfer_to_agent`. Realtime runs an agent's `before_tool_callback`, `on_tool_error_callback` and `after_tool_callback` around every tool call, as an ADK run does; ADK plugins do not run.

```python
from google.adk.agents import Agent as GoogleAgent


def limit_handoffs(tool, args, tool_context):
    if tool.name == "transfer_to_agent" and too_many_handoffs():
        return {"result": "Handoff refused: ask the caller what they think first."}
    return None  # let the tool run


supervisor = GoogleAgent(name="supervisor", model="gemini-3.1-flash-live-preview", sub_agents=[billing], before_tool_callback=limit_handoffs)
```

## Talking into a live call

Background work can report back into the call with `RealtimeCall`, in the process that runs the realtime pool
(every process of the single-process topology):

```python
from agentkernel.pipeline import RealtimeCall

call = RealtimeCall("room_01")
call.post_when_idle("[Team update] The build finished; 12 tests pass.", key="build")
```

Text sent into a call starts a model response, and on Gemini Live it cuts off one still being generated, so
`post_when_idle` waits for a quiet moment: the model is not responding, the caller is not speaking, the model
has answered what it was last given, and nothing has happened for a moment. Whichever agent has the call
answers the post. A post waits through a reconnect and for a call that has not connected yet, and is dropped
after `expires_after` seconds (10 minutes by default). A newer post with the same `key` replaces one still
waiting, and `call.withdraw(key)` drops one that no longer applies. Say whose words a post is (for example
`[Team update] ...`): the model takes it as it would the caller's words.

`RealtimeCall` also tells what the call is doing: `connected`, `quiet_for()` (seconds the call has been quiet,
or `None` while it is busy) and `agent_has_spoken` (whether the agent with the call has said anything since it
got it, known as soon as the model generates the words: a handoff policy can refuse an agent that hands the call
on without a word). See [Turn state](../architecture/realtime-internals.md#turn-state) for how quiet is decided.

## Watching a live call

A `RealtimeHook` sees what happens in the calls an agent serves, without reading logs:

```python
from agentkernel import RealtimeEvent, RealtimeHook

class Transcript(RealtimeHook):
    async def on_event(self, session, agent, event: RealtimeEvent) -> None:
        if event.type in ("caller_said", "agent_said"):
            print(event.agent or "caller", event.text)

    def name(self) -> str:
        return "transcript"

GoogleADKModule([pm]).realtime_hook(pm, [Transcript()])
```

| Event | When |
|---|---|
| `connected` / `disconnected` | The session's model socket opened (on the caller's first input) or closed (idle, failed, shut down) |
| `caller_said` | The caller's words in one turn, as the model transcribed them. Gemini Live only: the OpenAI adapter does not enable input transcription |
| `edge_text` | Text the edge sent into the call: what the caller typed, or a prompt the edge sends for them (the gateway's greeting) |
| `agent_said` | An agent's words in one turn, as they reached the edge; `interrupted` when the caller talked over it |
| `agent_changed` | The call moved to `event.agent`, and once for the agent it starts with |
| `reconnected` | The model socket dropped or stopped answering and was replaced, with `event.agent` still on the call (Gemini: reconnected with the conversation, the agent told the line dropped) |

Hooks are attached to the agent a call starts with and see its handoffs' turns too, named in `event.agent`.
They run one event at a time, in order, on the pool's loop but off the audio path; keep them short. A hook that
raises is logged, and the next one still runs.

## Example Projects

Complete working examples (with In-Memory, Kafka, NATS, and AWS SQS architectures) are available in the **examples/api/livekit-voice** directory. The `openai/handoffs` and `google/handoffs` variants show multi-agent handoffs with an internet support line (supervisor, billing and tech support). `google/handoffs` also refuses a handoff until the caller's account is verified (a `before_tool_callback`), confirms a technician visit from a background job with `RealtimeCall.post_when_idle`, and logs the call with a `RealtimeHook`.

## Limitations

- **No guardrails or pre/post hooks on realtime turns**: voice and chat turns go to the model socket directly, not through `Runtime.run()`, so input/output guardrails, pre/post hooks and the multimodal pre-hook do not run. [Realtime hooks](#watching-a-live-call) do: they observe the call, and cannot change what is said.
- **Tool limits**: OpenAI tools that need approval or have tool guardrails are not offered in realtime mode (a warning is logged), and ADK toolsets such as MCP are not supported. Plain function tools work on both frameworks.
- **One room per gateway**: each `LiveKitEdgeGateway` joins one room, and all audio in that room goes to one session.
- **History is held by the model connection**: the conversation lives in the model's own session (for a Google ADK transfer, Agent Kernel replays it into the new agent's socket).
  - **Google ADK**: a Gemini socket that drops, stalls or reaches the Live API's connection time limit (about 10 minutes) is replaced with the same agent, seeded with the conversation and a short note that the line dropped (see [Connection recovery](../architecture/realtime-internals.md#connection-recovery-google-adk)); what the caller says meanwhile is held and passed on. Only when every attempt fails, or the new sockets keep dropping, is the call failed.
  - **OpenAI**, and any adapter after a failed call: the next connection starts with no earlier turns, at the entry agent. So does a call evicted after five idle minutes.
  - The replayed conversation is text: tone of voice is not carried over, and a very long call replays a long history on every transfer or reconnect.
- **One LiveKit connection per agent**: with handoffs, every agent in the team is a participant for the whole call, and LiveKit bills connection minutes for each.
- **Single replicas**: one Agent Runner replica and one IOHandler process, as described above.
