# LiveKit Voice Integration

This example shows how to run an Agent Kernel instance connected directly to a LiveKit Room using WebRTC. This enables ultra-low-latency real-time voice streaming with the OpenAI Realtime API (`gpt-realtime` by default).

## Setup

You will need a LiveKit project (e.g. via [LiveKit Cloud](https://cloud.livekit.io/)). Obtain your WebSocket URL, API Key, and API Secret.

## Realtime Configuration

Agent Kernel handles realtime streaming pacing via the `execution.realtime` block in your config.

```yaml
execution:
  mode: realtime
  realtime:
    playback_lead_ms: 50    # Audio buffered ahead of playback at the edge (higher = smoother playback over slow brokers)
    input_batch_ms: 100     # Mic audio batched into this many milliseconds per input-queue message
```

## Build

Install dependencies using `uv` and the provided build script:

```bash
./build.sh
```

To install local dependencies in development mode (linking directly to your local Agent Kernel clone):

```bash
./build.sh local
```

## Run

Run this demo by first setting up your environment variables. Agent Kernel automatically binds environment variables starting with `AK_` to the configuration.

```bash
# Agent Kernel OpenAI credentials
export OPENAI_API_KEY="your-openai-api-key"

# Agent Kernel LiveKit credentials (AK_<SECTION>__<FIELD> binding)
export AK_LIVEKIT__URL="wss://your-project.livekit.cloud"
export AK_LIVEKIT__API_KEY="your-livekit-api-key"
export AK_LIVEKIT__API_SECRET="your-livekit-api-secret"
```

Every variant hosts LiveKit the way every other Agent Kernel integration hosts its platform: `EdgeLifecycleRESTRequestHandler` hosts
`LiveKitLifecycleAdapter`, which reads LiveKit's signed room webhooks, as `WebhookRESTRequestHandler` hosts the Slack
adapter. Each room is one call: `room_started` starts an edge and an Agent Kernel session for it (the room name is the
session id), and the edge ends the session when the last caller leaves. Nothing is fixed at start-up, so two callers in
two rooms get two separate calls.

The variants show the transports (`openai/in_memory`, `openai/kafka`, `openai/nats`, `openai/sqs`, `google/in_memory`,
`google/sqs`) and the agent features: the two `handoffs` variants (`openai/handoffs`, `google/handoffs`) show multi-agent
handoffs, with every agent shown as its own participant in the room, and `google/workflow` shows a fixed order of steps
written as an ADK `Workflow`. The agent that answers first is `livekit.agent` in each variant's `config.yaml`, as
`slack.agent` is for Slack. Run these commands from the variant you picked, and see its README.

### The webhook

LiveKit must be able to call `POST /livekit/webhook` on the IOHandler process (port 8000 by default). On a laptop, expose
it with a tunnel first, for example `ngrok http 8000`. In your LiveKit Cloud project open **Settings → Webhooks** and add
`https://<your-public-host>/livekit/webhook`, signed with the same API key you exported. `LiveKitLifecycleAdapter` verifies
every webhook with that key and answers 401 to anything else. Override `should_start(session_id)` to choose which rooms
get an agent (every room by default).

For the single-process `in_memory` example, start the server from its directory:

```bash
cd openai/in_memory
python server.py
```

For the broker examples (`openai/kafka`, `openai/nats`, `openai/sqs`) the pipeline is split across
two processes that share the queues, started from the variant's `app.py`:

```bash
cd openai/kafka        # or openai/nats, openai/sqs
python app.py io       # LiveKit edge + REST API
python app.py runner   # Agent Runner + the per-session native live sessions
```

Run the `runner` role as a **single replica** — its per-session live connection pool is process-local — and
one `io` process, since the edges run in the process that serves the webhook and replies come back to it. Start
the broker (Kafka, NATS, or LocalStack for SQS) before either process.

## Testing

Once the server is running and the webhook is set, join any room (for example `call_01`) from a frontend client or the
[LiveKit Agents Playground](https://agents-playground.livekit.io/). The agent joins within a second or two and greets
you. Leave the room and the session ends. Join a second room from another tab and you get a second, separate call.

To join as a human participant from the command line, mint a room token with the bundled helper
(same `AK_LIVEKIT__*` environment as the server) and pass it to the
[LiveKit Agents Playground](https://agents-playground.livekit.io/) or any LiveKit client:

```bash
uv run get_token.py call_01 alice
```

The first argument is the room, the second the participant's name. To test two calls at once, mint a token for a
second room with a different name (`uv run get_token.py call_02 bob`) and join it from another device or browser tab.

The script declares its own dependency (`livekit-api`) inline, so `uv run` installs it; no virtual
environment or `pyproject.toml` is needed in this directory.

## Caller transcription

The stream carries the caller's own finished lines (`InputTranscript` events) once the SDK's input transcription is on. The edge does not show them; a `LiveKitEdgeAdapter` subclass can, in `deliver_chunk`.

- **Google ADK** (`google/*`): on by default, nothing to do.
- **OpenAI** (`openai/*`): set `input_audio_transcription` in the session's model settings, for example `model_config={"initial_model_settings": {..., "input_audio_transcription": {"model": "gpt-4o-mini-transcribe"}}}` in `Module.run_options`. Without it no caller line is produced, and nothing fails.

## How it works

The `LiveKitEdgeAdapter` owns the room connection. Incoming mic audio is batched into ~100 ms
PCM16 frames and enqueued as `AgentRequestVoice` requests; the OpenAI Realtime runner appends them
to a native per-session live conversation (server VAD detects turn boundaries). The model's audio and
transcript deltas are written back to the output queue tagged with the `livekit` integration, and
the edge — registered as the `livekit` outbound adapter — plays them into the room.
