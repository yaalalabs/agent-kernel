---
sidebar_position: 10
---

# LiveKit Voice Integration

Agent Kernel supports real-time, ultra-low latency voice integrations via [LiveKit](https://livekit.io/). 

By treating LiveKit as an **Integration**, you can build an agent once (using CrewAI, LangGraph, OpenAI, etc.), equip it with tools and memory via Agent Kernel, and then use LiveKit to allow users to **talk to your agent over a real-time voice call**.

LiveKit handles the WebRTC voice connection, Speech-to-Text (STT), and Text-to-Speech (TTS), while Agent Kernel handles the intelligence, routing, and tools.

## Architecture

When you use the LiveKit integration:
1. The user speaks into their microphone via a LiveKit frontend.
2. LiveKit's **Speech-to-Text (STT)** plugin transcribes the voice into text.
3. The transcribed text is intercepted by our custom `AgentKernelLLM` bridge.
4. The bridge forwards the text to **Agent Kernel** (`AgentService().run(text)`).
5. Agent Kernel's selected agent processes the text and generates a response.
6. The response is sent back to LiveKit's **Text-to-Speech (TTS)** plugin.
7. The TTS plugin synthesizes the voice and streams it back to the user.

## Setup

First, ensure you have installed the LiveKit optional dependencies:

```bash
pip install "agentkernel[livekit]"
```

You will also need:
1. A free account on [LiveKit Cloud](https://cloud.livekit.io/).
2. Your LiveKit API keys (`AK_LIVEKIT__URL`, `AK_LIVEKIT__API_KEY`, `AK_LIVEKIT__API_SECRET`).
3. API keys for your preferred STT/TTS providers (e.g., `OPENAI_API_KEY`, `DEEPGRAM_API_KEY`, etc.).

## Configuration

In your `config.yaml`, configure which Agent Kernel agent should respond to LiveKit voice interactions, as well as your preferred STT and TTS providers:

```yaml
livekit:
  agent: "my-voice-agent"
  stt_provider: "deepgram"   # Options: deepgram, openai
  tts_provider: "openai"     # Options: openai, elevenlabs, google
  url: "wss://your-project-id.livekit.cloud" # Optional, can use LIVEKIT_URL env var
  api_key: "your_api_key"                    # Optional, can use LIVEKIT_API_KEY env var
  api_secret: "your_api_secret"              # Optional, can use LIVEKIT_API_SECRET env var
```

You can also set these via environment variables:
```bash
export AK_LIVEKIT__AGENT="my-voice-agent"
export AK_LIVEKIT__STT_PROVIDER="openai"
```

## Example Usage

Create a Python script (e.g., `server.py`) that initializes your Agent Kernel agent and starts the REST API. The `AgentLiveKitRequestHandler` will automatically launch the LiveKit background worker alongside your FastAPI server.

```python
import os
import logging
from agentkernel.api import RESTAPI
from agentkernel.openai import OpenAIModule
from agentkernel.livekit import AgentLiveKitRequestHandler
from agents import Agent as OpenAIAgent

logging.basicConfig(level=logging.INFO)

# 1. Define your Agent Kernel Agent
voice_agent = OpenAIAgent(
    name="my-voice-agent",
    handoff_description="Agent for voice interactions",
    instructions="You are a concise voice assistant. Do not use markdown or emojis.",
)

# 2. Register the agent with Agent Kernel
OpenAIModule([voice_agent])

# 3. Start the server with the LiveKit Handler
if __name__ == "__main__":
    RESTAPI.run([AgentLiveKitRequestHandler()])
```

> **Note:** The `AgentLiveKitRequestHandler` exposes a `/livekit/token` API endpoint on your FastAPI server. Your frontend (e.g., a React application or the LiveKit Agent Console) can hit this endpoint to generate secure access tokens for users joining the voice room.

Run the script in development mode:
```bash
uv run server.py
```

You can now connect to your LiveKit room using the [LiveKit Agents Playground](https://cloud.livekit.io/projects/p_/agents) or your own custom frontend to talk to your agent!
