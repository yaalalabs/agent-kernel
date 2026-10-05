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
    inject_history: false   # Whether to inject past chat session history when reconnecting
    history_limit: 20       # Maximum number of past messages to inject if inject_history is enabled
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
export AK_LIVEKIT__LIVEKIT_URL="wss://your-project.livekit.cloud"
export AK_LIVEKIT__API_KEY="your-livekit-api-key"
export AK_LIVEKIT__API_SECRET="your-livekit-api-secret"
```

Each variant lives in its own directory (`openai/in_memory`, `openai/kafka`, `openai/nats`,
`openai/sqs`, `google/in_memory`, `google/sqs`); run these commands from the variant you picked.

For the single-process `in_memory` example, start the server from its directory:

```bash
cd openai/in_memory
python server.py
```

For the broker examples (`openai/kafka`, `openai/nats`, `openai/sqs`) the pipeline is split across
two processes that share the queues, started from the variant's `app.py`:

```bash
cd openai/kafka        # or openai/nats, openai/sqs
python app.py io       # LiveKit edge gateway + REST API
python app.py runner   # Agent Runner + the per-session realtime sockets
```

Run the `runner` role as a **single replica** — its per-session socket pool is process-local — and
run exactly one `io` process per room, since each gateway joins the room as a participant. Start
the broker (Kafka, NATS, or LocalStack for SQS) before either process.

## Testing

Once the server is running, the agent will wait in the room. You can connect a frontend client (or use the [LiveKit Agents Playground](https://agents-playground.livekit.io/)) to connect to the exact same room and start speaking to your AI!

To join as a human participant from the command line, mint a room token with the bundled helper
(same `AK_LIVEKIT__*` environment as the server) and pass it to the
[LiveKit Agents Playground](https://agents-playground.livekit.io/) or any LiveKit client:

```bash
python get_token.py
```

## How it works

The `LiveKitEdgeGateway` owns the room connection. Incoming mic audio is batched into ~100 ms
PCM16 frames and enqueued as `AgentRequestVoice` requests; the OpenAI Realtime runner appends them
to a persistent per-session socket (server VAD detects turn boundaries). The model's audio and
transcript deltas are written back to the output queue tagged with the `livekit` integration, and
the gateway — registered as the `livekit` outbound adapter — plays them into the room.
