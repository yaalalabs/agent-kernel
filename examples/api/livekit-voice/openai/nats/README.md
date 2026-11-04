# Agent Kernel Realtime Voice over NATS JetStream (LiveKit)

This demo runs Agent Kernel's `REALTIME` execution pipeline for voice over WebRTC using LiveKit as the frontend gateway, powered by **NATS JetStream** as the backend message broker.

```
LiveKit WebRTC → IOHandler → AGENT_REQUESTS → Agent Runner → AGENT_REPLIES → IOHandler → LiveKit WebRTC
```

Because NATS is a heavy-duty broker transport, this example splits your application into **two separate processes** that share the streams. 

## What is NATS JetStream?

NATS is an ultra-fast, incredibly lightweight messaging system written in Go. While Kafka requires a massive amount of RAM and configuration, a NATS server can run efficiently in under 50 MiB of memory! 
"JetStream" is the persistence engine built into NATS. It provides message durability (similar to Kafka topics), ensuring no audio chunks are ever lost.

Like Kafka, NATS routes messages using strict lanes called **Subjects**. This means it perfectly groups all audio chunks for a single user's session into the same physical lane, making it highly efficient.

## Prerequisites

- Docker (for the NATS server and Valkey cache)
- `OPENAI_API_KEY` exported
- `AK_LIVEKIT__URL`, `AK_LIVEKIT__API_KEY`, and `AK_LIVEKIT__API_SECRET` exported (from your LiveKit Cloud dashboard)

> Note: If you are actively developing Agent Kernel core features, compile your local changes first by running `cd ../../../../../ak-py && make build`, and then use `./build.sh local` in this folder instead of `./build.sh`.

## Quickstart

This example is fully self-contained. The provided `nats_tester.py` script will automatically spin up a lightweight NATS server with JetStream enabled on your local machine using Docker.

### 1. Start the NATS Server (Terminal 1)
```bash
# Build the local environment
./build.sh

# Turn on the NATS Server, Valkey cache, and provision the streams
python nats_tester.py up
```
*(Leave this running. NATS is now available at `localhost:4222`)*

### 2. Start the Agent Runner (Terminal 2)
In a new terminal window, start the "Brain". This process connects to NATS, listens to the `AGENT_REQUESTS` stream, and pushes audio to OpenAI.
```bash
export OPENAI_API_KEY="sk-..."

# Start the runner
python app.py runner
```

### 3. Start the LiveKit Gateway (Terminal 3)
In a third terminal window, start the "Front Door". The `IOHandler` connects to LiveKit, catches user audio, and throws it onto the NATS stream.
```bash
export AK_LIVEKIT__URL="wss://your-project.livekit.cloud"
export AK_LIVEKIT__API_KEY="..."
export AK_LIVEKIT__API_SECRET="..."

# Start the IO Handler
python app.py io
```

## Testing and Cleanup

Connect to `room_01` in your LiveKit Sandbox dashboard and speak. Your voice will route through NATS to OpenAI and back!

When finished, shut down Terminal 2 and 3 using `Ctrl + C`. Then in Terminal 1, run:
```bash
python nats_tester.py down
```
This safely deletes the NATS Docker container.

## Architecture Note: The Python Polling Limitation

Unlike Kafka, the official `nats-py` Python client lacks a mechanism to instantly pull a message from *any* partition simultaneously. Instead, the Agent Kernel NATS Transport (`NatsTransportConsumer`) has to simulate this by using a Python `for` loop to manually check each partition one-by-one with a 50ms timeout.

If you set `partitions: 32` in `config.yaml`, this Python loop introduces up to **1.6 seconds of artificial polling latency** as it sweeps across empty partitions looking for the next audio chunk. Because `REALTIME` voice requires streaming 20+ chunks per second, this latency completely starves the audio player, causing robotic stuttering.

**The Local Fix:** For local testing, `config.yaml` is set to `partitions: 1`. With only 1 partition, the Python loop has zero sweep delay and fetches audio instantly, making the voice perfectly smooth.

**The Production Fix:** Because of this specific Python library limitation, it is highly recommended to use **Kafka** or **AWS SQS** for heavy production `REALTIME` workloads in Agent Kernel. If you must use NATS in production, you should write your consumer in Go using the native NATS JetStream client, which does not suffer from this loop latency.
