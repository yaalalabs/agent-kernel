# Agent Kernel Realtime Voice over Kafka (LiveKit)

This demo runs Agent Kernel's `REALTIME` execution pipeline for voice over WebRTC, using LiveKit as the frontend gateway and a Kafka broker to connect the pipeline.

```
LiveKit WebRTC → IOHandler → agent-input → Agent Runner → agent-output → IOHandler → LiveKit WebRTC
```

Because Kafka is a high-performance broker transport, the pipeline is split across **two separate processes** that share the queues. This demonstrates true microservice scalability for Realtime voice.

## Prerequisites

- Docker (for the Kafka broker and Valkey cache)
- `OPENAI_API_KEY` exported
- `AK_LIVEKIT__URL`, `AK_LIVEKIT__API_KEY`, and `AK_LIVEKIT__API_SECRET` exported (from your LiveKit Cloud dashboard)

> Note: If you are actively developing Agent Kernel core features (like `RealtimeAgentRunner`), compile your local changes first by running `cd ../../../../../ak-py && make build`, and then use `./build.sh local` in this folder instead of `./build.sh`.

## Quickstart

This example is fully self-contained. The provided `kafka_tester.py` script will automatically spin up a lightweight Kafka broker on your local machine using Docker.

### 1. Start the Kafka Server (Terminal 1)
```bash
# Build the local environment
./build.sh

# Turn on the Kafka Broker, Valkey cache, and provision the topics
python kafka_tester.py up
```
*(Leave this running. Kafka is now available at `localhost:9092`)*

### 2. Start the Agent Runner (Terminal 2)
In a new terminal window, start the "Brain" of the operation. This process connects to Kafka, listens for incoming audio chunks, and streams them to the OpenAI Realtime API.
```bash
export OPENAI_API_KEY="sk-..."

# Start the runner
python app.py runner
```

### 3. Start the LiveKit Gateway (Terminal 3)
In a third terminal window, start the "Front Door". The `IOHandler` connects to LiveKit, catches user audio via WebRTC, and throws it onto the Kafka bullet train.
```bash
export AK_LIVEKIT__URL="wss://your-project.livekit.cloud"
export AK_LIVEKIT__API_KEY="..."
export AK_LIVEKIT__API_SECRET="..."

# Start the IO Handler
python app.py io
```

## Testing it Live

Once all three terminals are running, open your LiveKit Sandbox dashboard or custom frontend. Connect to `room_01`. 
When you speak, Terminal 3 grabs the audio, passes it to Terminal 2 via Kafka, OpenAI processes the speech, and the AI's voice is instantly streamed back to your headset!

## Clean Up

When you are finished testing, gracefully shut down Terminal 2 and Terminal 3 by pressing `Ctrl + C`.
Then, in Terminal 1, run the following to destroy the Docker containers and clean up your laptop's memory:

```bash
python kafka_tester.py down
```

## The RealtimeConnectionPool Architecture

This example perfectly demonstrates the necessity of the `RealtimeConnectionPool`.
Because Kafka partitions distribute incoming audio chunks, the `AgentRunner` uses a process-local memory dictionary (`RealtimeConnectionPool`) to ensure that consecutive audio chunks from the exact same LiveKit session find the exact same persistent WebSocket connection to Google/OpenAI, even if the chunks are picked up milliseconds apart!
