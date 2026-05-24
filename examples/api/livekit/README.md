# LiveKit Voice & Vision Integration Example

This example demonstrates how to use **LiveKit** as a voice and vision interface for your Agent Kernel agents. It provides a real-time, low-latency conversational experience with optional webcam support.

## Overview

This integration allows users to talk to an agent using their microphone and optionally show things via their webcam. The agent responds with a synthesized voice (TTS).

- **Voice**: STT (Deepgram/OpenAI) -> Agent Kernel -> TTS (OpenAI/ElevenLabs/Google)
- **Vision**: Webcam frames captured per voice turn -> Agent Kernel Multimodal Pipeline -> Agent Response

## Prerequisites

1. **LiveKit Cloud Account**: Create a project at [cloud.livekit.io](https://cloud.livekit.io/)
2. **LiveKit Credentials**: URL, API Key, and API Secret from your project settings.
3. **STT/TTS Provider API Keys**:
   - OpenAI (for TTS and optionally STT)
   - Deepgram (recommended for STT)
   - ElevenLabs or Google (optional for TTS)

## Setup

### 1. Configure Environment Variables

Create a `.env` file or export these variables:

```bash
# LiveKit Credentials
export AK_LIVEKIT__URL="wss://your-project.livekit.cloud"
export AK_LIVEKIT__API_KEY="your_api_key"
export AK_LIVEKIT__API_SECRET="your_api_secret"

# Provider Keys
export OPENAI_API_KEY="your_openai_key"
export DEEPGRAM_API_KEY="your_deepgram_key"
```

### 2. Configure Agent Kernel

Create `config.yaml`:

```yaml
livekit:
  agent: "my-voice-agent"
  stt_provider: "deepgram"       # deepgram or openai
  tts_provider: "openai"         # openai, elevenlabs, or google
  vision_enabled: true           # Set to true to enable webcam vision

# Required when vision_enabled is true
multimodal:
  enabled: true                  # Required to process webcam frames
  description_model: "gpt-4o"    # Vision model to describe frames
```

## Build & Run

Install dependencies:

```bash
./build.sh
```

Start the server:

```bash
uv run server.py
```

The server will start on `http://localhost:8000`.

## Testing

### 1. Get a Token
Visit: `http://localhost:8000/livekit/token?room=demo-room&identity=user1`
Copy the returned `token`.

### 2. Connect via LiveKit Playground
1. Go to your [LiveKit Cloud Console](https://cloud.livekit.io/).
2. Select your project -> **Agents** -> **Playground**.
3. Click **Connect** and paste your token (or join the room `demo-room` as `user1`).
4. **Talk**: Start speaking. The agent should respond.
5. **Vision**: Turn on your camera. Ask "What do you see?". The agent should describe your surroundings.

## Troubleshooting

### Connection Errors
- Ensure `AK_LIVEKIT__URL` starts with `wss://`.
- Check if your API Key and Secret are correct in the console.

### No Voice Response
- Check server logs for STT/TTS errors (e.g., "Authentication Fails" or "Quota Exceeded").
- Ensure your microphone is not muted and permissions are granted in the browser.

### Vision Not Working
- Ensure `vision_enabled: true` AND `multimodal.enabled: true` are set in `config.yaml`.
- Verify you have provided a vision-capable model in `multimodal.description_model` (like `gpt-4o`).
- Check server logs for "Attaching webcam frame" messages.

## Resources

- [LiveKit Agents Documentation](https://docs.livekit.io/agents/)
- [Agent Kernel Documentation](../../../docs/)
