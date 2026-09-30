# LiveKit

The LiveKit integration allows you to deploy Agent Kernel agents as Realtime Voice agents that can participate in WebRTC voice calls. This integration uses LiveKit as the frontend gateway to stream incredibly fast, low-latency audio directly to and from your agents over a message broker pipeline.

## Overview

The `LiveKitEdgeGateway` handles Realtime WebRTC sessions with end-users. Unlike standard text integrations, LiveKit requires the `REALTIME` pipeline execution mode and a persistent broker (like Kafka, SQS, or NATS) to securely transmit streaming audio chunks between the LiveKit server and the Agent Runner.

## How It Works

1. A user connects to a LiveKit room and starts speaking.
2. The `LiveKitEdgeGateway` (running in the IOHandler process) intercepts the audio and buffers it into chunks.
3. The IOHandler places the audio chunks onto the `AGENT_REQUESTS` queue.
4. The Agent Runner receives the chunks, utilizing a `RealtimeConnectionPool` to maintain an active WebRTC connection to OpenAI or Gemini.
5. The LLM's audio response is pushed onto the `AGENT_REPLIES` queue.
6. The `LiveKitEdgeGateway` receives the response and plays it back directly into the user's LiveKit room.

## Features

- **Realtime Voice**: True bi-directional streaming audio over WebRTC.
- **Barge-in Support**: Users can interrupt the AI at any time. The `LiveKitEdgeGateway` automatically clears buffered AI audio upon detecting a user barge-in.
- **Distributed Architecture**: Scales horizontally via message brokers. `LiveKitEdgeGateway` acts as the edge frontend, keeping heavy LLM inference isolated in the Agent Runner backend.

## Configuration Steps

### 1. LiveKit Cloud Setup

1. Create a free account at [LiveKit Cloud](https://cloud.livekit.io/).
2. Create a new project.
3. Obtain your API URL, API Key, and API Secret from the project settings.

### 2. Required Environment Variables

```bash
export AK_LIVEKIT__URL="wss://<your-project>.livekit.cloud"
export AK_LIVEKIT__API_KEY="your_api_key"
export AK_LIVEKIT__API_SECRET="your_api_secret"
```

## Implementation

### Basic Integration

Integrations run on the queue execution pipeline, so they are mounted with `IOHandler.run(...)`.

```python
from agentkernel.integration.livekit.adapter import LiveKitEdgeGateway
from agentkernel.pipeline import IOHandler

if __name__ == "__main__":
    # Start the Front Door IO Handler with LiveKit Edge Gateway
    IOHandler.run(handlers=[LiveKitEdgeGateway()])
```

Because of the heavy distributed nature of real-time voice, you must run the Agent Runner in a completely separate process (or container):

```python
from agents import Agent as OpenAIAgent
from agentkernel.pipeline.agent_runner import AgentRunner
from agentkernel.openai import OpenAIModule

agent = OpenAIAgent(
    name="voice_assistant",
    instructions="You are a helpful voice assistant.",
)
OpenAIModule([agent])

if __name__ == "__main__":
    # Start the Agent Runner backend
    AgentRunner.run()
```

:::note Execution Mode
LiveKit requires the Agent Kernel execution mode to be set to `realtime`. Standard async/sync text modes will not work. Ensure you have `execution.mode: realtime` set in your `config.yaml`.
:::

## Example Projects

Complete working examples (with In-Memory, Kafka, NATS, and AWS SQS architectures) are available in the **examples/api/livekit-voice** directory.
