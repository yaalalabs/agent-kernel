# LiveKit Voice Integration

LiveKit is a realtime voice integration for OpenAI Agents SDK and Google ADK agents. The `LiveKitEdgeGateway` joins a LiveKit room, sends the user's audio and chat text to the agent, and plays the model's streamed audio and transcript back to the room through Agent Kernel's realtime execution pipeline.

## Overview

The gateway runs in `realtime` execution mode. It works on every queue transport:

- **`in_memory` (single process)**: the gateway, the Agent Runner and the Response Handler run in one process. This is the simplest setup and the recommended first run.
- **A broker (`kafka`, `nats`, `sqs`)**: the gateway (IOHandler process) and the Agent Runner run as two processes that share the queues.

Only OpenAI Agents SDK and Google ADK agents can run in realtime mode. They are the only adapters with a realtime runner (`OpenAIRealtimeRunner`, `GoogleADKRealtimeRunner`). OpenAI voice agents use native `agents.realtime.RealtimeAgent`; their model is configured on the realtime session. Google ADK agents name a Gemini Live model.

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
from agents.realtime import RealtimeAgent as OpenAIAgent

from agentkernel.framework.openai import OpenAIModule
from agentkernel.integration.adapter import GatewayRunner
from agentkernel.livekit import LiveKitEdgeGateway
from agentkernel.pipeline import IOHandler

agent = OpenAIAgent(
    name="voice_assistant",
    instructions="You are a helpful voice assistant.",
)
OpenAIModule([agent]).run_options(agent, config={"model_settings": {"model_name": "gpt-realtime"}})

if __name__ == "__main__":
    IOHandler.run(gateways=[GatewayRunner(LiveKitEdgeGateway(session_id="room_01"))])
```

### OpenAI native realtime configuration and migration

Use `agents.realtime.RealtimeAgent` for voice; ordinary `agents.Agent` remains for text runs.
The adapter does not convert text agents into voice agents. Move the model from `Agent(model=...)`
to `Module.run_options(voice, config={"model_settings": {"model_name": ...}})`.
Native `config` and `model` go to `RealtimeRunner`; `model_config` goes to its session `run()`.
Only static run options are used for a call. For example, add
`"input_audio_transcription": {"model": "gpt-4o-mini-transcribe"}` to `config.model_settings`
when caller transcripts are needed. Do not override session tools/handoffs in model settings;
declare them on `RealtimeAgent` so AK can supply their execution context.

AK supports PCM16 mono at 24 kHz and the SDK’s default `async_tool_calls=True`.
The ordinary lifecycle `hooks` field is not executed by this version of the native realtime SDK.
Agent output guardrails can interrupt streaming output; they cannot retract audio already heard.
The adapter’s playback tracker follows paced queue emission, which estimates playback rather than
acknowledging what reached the caller. OpenAI automatic resumption is not added by this migration.

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

### A room per session

To give each meeting a room of its own, opened when someone joins and closed when the meeting ends, host one
`GatewayRunner` per meeting and keep them by meeting in your application. A runner hosts one gateway in the process of the
Response Handler, as `IOHandler.run(gateways=[GatewayRunner(gateway)])` does for a fixed list, and `stop()` ends it from
any thread, even before it has started:

```python
import threading

from agentkernel.integration.adapter import GatewayRunner
from agentkernel.livekit import LiveKitEdgeGateway

runners: dict[str, GatewayRunner] = {}
lock = threading.Lock()


def open_room(meeting_id: str) -> LiveKitEdgeGateway:
    with lock:
        if meeting_id in runners:
            return runners[meeting_id].adapter
        runner = GatewayRunner(LiveKitEdgeGateway(session_id=meeting_id, agent_name="pm"))
        runners[meeting_id] = runner

    def host():
        try:
            runner.start()                    # blocks until the room is left
        finally:
            with lock:                        # forget it, unless a newer room has taken its place
                if runners.get(meeting_id) is runner:
                    del runners[meeting_id]

    threading.Thread(target=host, daemon=True).start()
    return runner.adapter


def close_room(meeting_id: str) -> None:
    with lock:
        runner = runners.pop(meeting_id, None)
    if runner:
        runner.stop(timeout=10)               # outside the lock: it waits for the team to leave
```

A room that could not be joined makes `start()` raise; the thread above forgets it, so the next join tries again. A
runner still hosting a room when the server shuts down leaves with it.

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

A Google ADK call runs on ADK's own live engine (`Runner.run_live`), which needs `google-adk` 2.7 or later. The
call's ADK `RunConfig` is the one its starting agent declares as a run option, the same option a non-live run
reads, and ADK applies it to every socket of the call, the sockets a transfer or a reconnect opens included. It
sets, for example, how Gemini detects the caller's turns and which languages it transcribes:

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

The whole `RunConfig` reaches ADK, `session_resumption` included. Agent Kernel only turns on transcription of
both sides when it is unset, since the call's transcripts depend on it. The starting agent's ADK `Runner` options
(`plugins`, `memory_service`, `artifact_service`, `credential_service`) reach the call's `Runner` too, as on a
non-live run. A run-options factory is not called for realtime calls: the call has no per-run requests to give it.

Each agent speaks in the voice of its model: give it `Gemini(model=..., speech_config=...)`. ADK's live run does
not read `generate_content_config.speech_config`.

```python
from google.adk.agents import Agent as GoogleAgent
from google.adk.models import Gemini
from google.genai import types

billing = GoogleAgent(
    name="billing",
    model=Gemini(
        model="gemini-3.1-flash-live-preview",
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Charon"))
        ),
    ),
    instruction="Answer billing questions.",
)
```

### Tools and framework context

Realtime tool calls receive the session's `framework_context` as their run context, as unary runs
do (`wrapper.context` on OpenAI), and `ToolContext.get()` works as usual. Unlike a unary run, a
realtime tool call does not write `framework_context` back, so changes a tool makes to it are not
persisted.

## Multi-agent handoffs

One call can move between several native voice agents. Register only the entry agent:

- **OpenAI Agents SDK**: `RealtimeAgent(handoffs=[...])`, run by the SDK’s native `RealtimeRunner`. Each agent's handoffs are offered to the model as functions (`transfer_to_billing`, ...).
- **Google ADK**: `LlmAgent(sub_agents=[...])`. ADK's own rules decide who can transfer to whom: an agent to its sub-agents, and back to its parent or across to its peers unless `disallow_transfer_to_parent` / `disallow_transfer_to_peers` is set.

```python
from agents.realtime import RealtimeAgent as OpenAIAgent

from agentkernel.framework.openai import OpenAIModule
from agentkernel.integration.adapter import GatewayRunner
from agentkernel.livekit import LiveKitEdgeGateway
from agentkernel.pipeline import IOHandler

supervisor = OpenAIAgent(name="supervisor", instructions="Route the caller to billing or tech support.")
billing = OpenAIAgent(name="billing", instructions="Answer billing questions.", handoffs=[supervisor])
tech_support = OpenAIAgent(name="tech_support", instructions="Fix connection problems.", handoffs=[supervisor])
supervisor.handoffs = [billing, tech_support]

OpenAIModule([supervisor]).run_options(supervisor, config={"model_settings": {"model_name": "gpt-realtime"}})

if __name__ == "__main__":
    IOHandler.run(gateways=[GatewayRunner(LiveKitEdgeGateway(session_id="room_01", agent_name="supervisor"))])
```

The conversation, and the context the caller has given, carries over to the agent that takes the call. On Google ADK, the agent that takes the call sees its teammates' turns with who said them (`[billing] said: ...`), as ADK presents another agent's turns, so agents can put questions to each other and answer them. ADK fences those turns, tool results included, as data the agent must never take instructions from: tell the agent taking the call who it is and why it has the call in its own `instruction` (an `InstructionProvider` is built again each time it takes the call), not in a transfer's result.

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
| Handoff | Same model socket; the session is switched to the new agent's instructions and tools | ADK's own transfer: a new Gemini Live socket for the new agent, given the conversation so far |
| Gap the caller hears | None | About 1 to 2 seconds. ADK keeps the old socket for about a second after the transfer: what the caller says then goes to the agent handing over and is not heard by the new one; after that, it waits for the new agent |
| Voice and model | Every agent uses the realtime session’s model and voice | Each agent its own model and voice (`Gemini(model=..., speech_config=...)`) |
| Rejected when the call connects | A handoff with `input_filter` or `nest_handoff_history`, which realtime cannot apply | Nothing by Agent Kernel: ADK's live run decides when an agent's socket opens |

For how handoffs flow through the pipeline, see [Realtime Voice Internals](../architecture/realtime-internals.md).

### Refusing a handoff

Use each framework’s native controls to decide which transfers are allowed:

- **OpenAI Agents SDK**: use `handoff(agent, is_enabled=...)` to control whether the SDK offers a transfer. `on_handoff` follows native SDK error handling; raising can fail the call and is not a recoverable refusal mechanism.
- **Google ADK**: give the agent a `before_tool_callback` that returns a result for `transfer_to_agent`. ADK runs its plugins and the agent's `before_tool_callback`, `on_tool_error_callback` and `after_tool_callback` around every tool call, as on any ADK run.

```python
from google.adk.agents import Agent as GoogleAgent


def limit_handoffs(tool, args, tool_context):
    if tool.name == "transfer_to_agent" and too_many_handoffs():
        return {"result": "Handoff refused: ask the caller what they think first."}
    return None  # let the tool run


supervisor = GoogleAgent(name="supervisor", model="gemini-3.1-flash-live-preview", sub_agents=[billing], before_tool_callback=limit_handoffs)
```

## Talking into a live call

Application code outside a tool call (a realtime observer, a webhook, a timer) can speak into the call with
`RealtimeCall`, in the process that runs the realtime pool (every process of the single-process topology):

```python
from agentkernel.pipeline import RealtimeCall

call = RealtimeCall("room_01")
sent = await call.send_if_quiet("[Team update] The build finished; 12 tests pass.")
```

Text sent into a call starts a model response, and on Gemini Live it cuts off one still being generated, so
`send_if_quiet` sends only into a quiet call: connected and not recovering, no tool running, no output still to play,
the caller not speaking, the model not taken to owe a reply (to the caller's turn, typed text, a tool result or earlier
application text), and nothing having happened for a moment. It returns whether it sent the text. Declined, nothing is
kept: Agent Kernel keeps no queue of application text, so whether to try again, when, and when to give up are the
application's (keep what is waiting per call, so it outlives a renewed model connection). Whichever agent has the call
answers. Say whose words the text is (for example `[Team update] ...`): the model takes it as it would the caller's words.

- **One step on the pool's loop.** The check and the send run together on the realtime pool's event loop, whichever
  loop awaits `send_if_quiet` (a web handler's, or the pool's own in an observer's task), so the call cannot change
  between them. It never blocks the pool's loop.
- **Sent is not heard.** The caller may start speaking right after; the usual barge-in applies.
- **A failing send raises**; without a pool or a live call, `send_if_quiet` returns `False`.
- **The owed reply is inferred.** Between being given something and its first output, the model is silent: a reply is
  taken to be owed while it has generated nothing since, for at most 15 seconds, after which the pool stops waiting (the
  model may never answer). The pool does not take that as an answer having come.

`RealtimeCall` also tells what the call is doing: `connected`, `quiet_since()` / `quiet_for()` (when the call's quiet
stretch began, and for how long, or `None` while it is busy) and `agent_has_spoken` (whether the agent with the call
has said anything since it got it, known as soon as the model generates the words: a handoff policy can refuse an
agent that hands the call on without a word). It tells when each last happened, too: `last_caller_input_at` (the
caller spoke, or the edge sent text), `last_agent_change_at` and `last_tool_result_at`, in epoch seconds, `None` without
a call. See [Turn state](../architecture/realtime-internals.md#turn-state) for how quiet is decided.

Text that only applies to one quiet moment (a nudge) passes the stretch it was made for:
`send_if_quiet(text, quiet_since=stretch)`, with `stretch` from `quiet_since()`. It is sent only while the call is still
in that stretch; anything happening (the caller, the model, a handoff, a tool result, other text, a new model
connection) starts a new one.

## Tools that wait for long work

A realtime tool can be an ordinary `async` function that awaits long work, such as another registered agent's run,
and returns its result. The model gets that result as the tool call's answer, exactly as for a quick tool:

```python
import uuid

from agentkernel.core import AgentRequestText, AgentService, ToolContext


async def request_research(question: str) -> str:
    """Ask the Researcher one question and return its answer; it can take a minute."""
    call_session = ToolContext.get().session.id
    service = AgentService()
    service.select(f"{call_session}.research.{uuid.uuid4().hex[:8]}", "researcher")  # a session of its own
    reply = await service.run_multi([AgentRequestText(prompt=f"Research question: {question}")])
    return str(reply)
```

- **Where it runs**: on the realtime pool's loop, which also paces every call's audio. Awaiting network I/O (an SDK's
  async client) yields that loop, so other calls keep playing; blocking work must go to `asyncio.to_thread`, or every
  call waits behind it (the pool logs a loop blocked for over a second).
- **Sessions**: a realtime tool runs inside the call's AK session and holds its lock until it returns, so the agent
  it asks must run in a session of its own; running it in the call's session would wait on that lock for ever. Tool
  calls the model makes in one turn share the call's session, so they run one after another.
- **While it waits**: the call counts as busy (`is_responding`). `send_if_quiet` declines and
  `RealtimeCall.quiet_for()` is `None` until the result is sent. The caller's audio still reaches the model; what the model
  does with it while its tool call is open is the model's own behaviour. Gemini Live is not taken for stalled
  meanwhile: its wait for an answer starts when the result is sent. On Google ADK, ADK reads nothing from the
  socket while its tools run, so the caller's words and interruptions during the wait arrive after it. The model may speak before it calls the tool,
  but the model decides when it makes the call, so that speech is not guaranteed to be heard first.
- **Failures and time limits**: an agent's failed run comes back from `run_multi` as error text, as on every other
  surface; detect it through the framework's own signal (with the OpenAI Agents SDK, `RunHooks.on_agent_end` is called
  only for a run that finished). Agent Kernel sets no overall time limit on a tool: bound the wait with
  `asyncio.timeout` where the caller cannot wait longer than the framework's own request limits.
- **Ending the call**: `RealtimeCall.close()`, an idle eviction or a pool shutdown cancels the tool calls still
  running for the connection (`asyncio.CancelledError` inside them, which unwinds the nested run and its session
  lock) and gives them 2 seconds to unwind. A result that comes after the connection closed or its socket failed is
  not sent.
- **A dropped socket (Google ADK)**: ADK notices a lost socket only once its tools have returned, so the result is
  in the conversation the restarted run is given, however long the tool took, and the agent does not run it again.

Agent Kernel decides no policy here: no retries, no wording, no time limit.

## Watching a live call

A `RealtimeObserver` sees what happens in the process's realtime calls, without reading logs. It watches; it
cannot change what is said. Register it before the calls begin:

```python
from agentkernel import RealtimeEvent, RealtimeObserver
from agentkernel.pipeline import RealtimeCall

class Transcript(RealtimeObserver):
    async def on_event(self, session, agent, event: RealtimeEvent) -> None:
        if event.type in ("caller_said", "agent_said"):
            print(event.agent or "caller", event.text)

    def name(self) -> str:
        return "transcript"

RealtimeCall.observe(Transcript())
```

| Event | When |
|---|---|
| `connected` / `disconnected` | The session's model connection opened (on the caller's first input) or closed (idle, failed, shut down). A new connection starts at the entry agent and remembers nothing |
| `caller_said` | The caller's words in one turn, as the model transcribed them. Gemini Live, or OpenAI when `input_audio_transcription` is configured in native session model settings |
| `edge_text` | Text the edge sent into the call: what the caller typed, or a prompt the edge sends for them (the gateway's greeting) |
| `agent_said` | An agent's words in one turn, as they reached the edge; `interrupted` when the caller talked over it |
| `agent_changed` | The call moved to `event.agent`, and once for the agent it starts with |
| `reconnected` | Within one connection, the model socket dropped or stopped answering and was replaced, with `event.agent` still on the call; reported once the new socket is answering (Gemini: restarted with the conversation, the agent told the line dropped; a socket ADK resumes itself is not reported) |

An observer sees every call the process connects after it is registered (`RealtimeCall.unobserve` stops it for later
calls), handoffs' turns included, named in `event.agent`; `agent` is the agent the call started with. Observers run
one event at a time, in order, on the pool's loop but off the audio path; keep them short. One that raises is logged,
and the next one still runs.

To act on a call that has gone quiet (nudge a stalled agent, say), read `RealtimeCall.quiet_for()`: an observer can
start a task on `connected` that checks it every second or so and cancel it on `disconnected`, so the application
needs no thread of its own. Whether to act, and what to say, is the application's; text sent with
`send_if_quiet(..., quiet_since=...)` is declined if anything happened since the quiet stretch began.

## Example Projects

Complete working examples (with In-Memory, Kafka, NATS, and AWS SQS architectures) are available in the **examples/api/livekit-voice** directory. The `openai/handoffs` and `google/handoffs` variants show multi-agent handoffs with an internet support line (supervisor, billing and tech support). `google/handoffs` also refuses a handoff until the caller's account is verified (a `before_tool_callback`), books a technician with an `async` tool that waits for the dispatch system's confirmation, and logs the call with a `RealtimeObserver`.

## Limitations

- **No guardrails or pre/post hooks on realtime turns**: voice and chat turns go to the model socket directly, not through `Runtime.run()`, so input/output guardrails, pre/post hooks and the multimodal pre-hook do not run. [Realtime observers](#watching-a-live-call) see the call, and cannot change what is said.
- **Tool limits**: OpenAI runs function tool input guardrails and agent output guardrails natively. Tool output guardrails are not applied by the installed realtime SDK, and AK has no realtime approval decision surface: either configuration raises before connect. MCP/toolset scoping and non-function tools also raise explicitly. On Google ADK, ADK's live runner resolves an agent's tools as on any run; toolsets such as MCP have not been tested in a live call. Plain function tools work on both frameworks.
- **One room per gateway**: each `LiveKitEdgeGateway` joins one room, and all audio in that room goes to one session; an application that gives each meeting a room hosts one runner per room.
- **History is held by the call**: on OpenAI, in the model's own session; on Google ADK, in the call's ADK session, which ADK gives each new socket.
  - **Google ADK**: ADK resumes a dropped socket itself when it holds a session resumption handle. A socket that still drops, stalls or reaches the Live API's connection time limit (about 10 minutes) is replaced by starting ADK's run again with the same agent, the conversation and a short note that the line dropped (see [Connection recovery](../architecture/realtime-internals.md#connection-recovery-google-adk)); what the caller says meanwhile waits for the new socket. Only when the restarted runs keep dropping is the call failed.
  - **OpenAI**, and any adapter after a failed call: the next connection starts with no earlier turns, at the entry agent. So does a call evicted after five idle minutes.
  - The conversation a new Gemini socket is given is text: tone of voice is not carried over, and a very long call sends a long history on every transfer or restart.
  - **Words said with a transfer**: ADK records an agent's words when Gemini marks their transcription finished, or at the end of the turn; words said in a turn that ends in a transfer may not reach the agent taking the call.
- **One LiveKit connection per agent**: with handoffs, every agent in the team is a participant for the whole call, and LiveKit bills connection minutes for each.
- **Single replicas**: one Agent Runner replica and one IOHandler process, as described above.
- **A waiting tool holds its turn**: while a tool awaits long work the agent says nothing more, and on Google ADK nothing the model sends is read until the tool returns (see [Tools that wait for long work](#tools-that-wait-for-long-work)).
