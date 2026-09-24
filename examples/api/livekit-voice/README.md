# LiveKit Voice Integration

This example shows how to run an Agent Kernel instance connected directly to a LiveKit Room using WebRTC. This enables ultra-low-latency real-time voice streaming with the OpenAI Realtime API (`gpt-realtime` by default).

## Setup

You will need a LiveKit project (e.g. via [LiveKit Cloud](https://cloud.livekit.io/)). Obtain your WebSocket URL, API Key, and API Secret.

## Build

Install dependencies using `uv` and the provided build script:

```bash
./build.sh
```

To install local dependencies in development mode (linking directly to your local Agent Kernel clone):

```bash
./build.sh local
```

> **Developing against a local Agent Kernel clone:** `./build.sh local` installs the wheel from
> `ak-py/dist`, and `uv run server.py` re-syncs that wheel on every launch. After changing anything
> under `ak-py/src`, rebuild the wheel or you will keep running the old code:
>
> ```bash
> (cd ../../../ak-py && uv build --wheel) && ./build.sh local
> ```

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

Start the server:

```bash
python server.py
```

## Testing

Once the server is running, the agent will wait in the room. You can connect a frontend client (or use the [LiveKit Agents Playground](https://agents-playground.livekit.io/)) to connect to the exact same room and start speaking to your AI!

For a headless smoke test, run the bundled client in a second terminal (same `AK_LIVEKIT__*`
environment as the server). It joins as a human participant, publishes a mic track to trigger the
agent's greeting, and prints the transcript the agent streams back:

```bash
python test_gw.py
```

## How it works

The `LiveKitEdgeGateway` owns the room connection. Incoming mic audio is batched into ~100 ms
PCM16 frames and enqueued as `AgentRequestVoice` requests; the OpenAI Realtime runner appends them
to a persistent per-session socket (server VAD detects turn boundaries). The model's audio and
transcript deltas are written back to the output queue tagged with the `livekit` integration, and
the gateway — registered as the `livekit` outbound adapter — plays them into the room.
