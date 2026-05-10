# LiveKit Voice Integration Demo

This example demonstrates how to use **LiveKit** as a voice interface for your Agent Kernel agents, running identically to the Slack and WhatsApp integrations.

By passing `AgentLiveKitRequestHandler` to `RESTAPI.run()`, Agent Kernel automatically:
1. Exposes a `/livekit/token` endpoint for your frontend client to connect securely.
2. Runs the LiveKit `VoicePipelineAgent` in the background within the FastAPI event loop.

## How it works

1. Your frontend fetches a secure token from `GET /livekit/token?room=my-room&identity=user1`.
2. The frontend connects to the LiveKit Room.
3. The background LiveKit Worker uses your configured Speech-to-Text provider (e.g. Deepgram or OpenAI) to transcribe the user's voice to text.
4. The custom `AgentKernelLLM` intercepts this text and hands it over to **Agent Kernel**.
5. Agent Kernel routes the text to your configured agent (with all memory/hooks preserved).
6. The generated text reply is sent to your configured Text-to-Speech provider (e.g. OpenAI or ElevenLabs), which synthesizes it into a voice stream and plays it to the user.

## Setup

1. Create a free account on [LiveKit Cloud](https://cloud.livekit.io/) and create a project.
2. Generate API Keys in the project settings.
3. Get API keys for OpenAI and Deepgram.
4. Copy `.env.example` to `.env` and fill in the values:

```bash
LIVEKIT_URL=wss://your-project-id.livekit.cloud
LIVEKIT_API_KEY=your_livekit_api_key
LIVEKIT_API_SECRET=your_livekit_api_secret

OPENAI_API_KEY=your_openai_api_key
DEEPGRAM_API_KEY=your_deepgram_api_key
```

## Running the Demo

1. Install dependencies:
```bash
uv sync
```

2. Run the REST API:
```bash
uv run server.py
```

3. The server will start on `http://0.0.0.0:8000`. You can get a test token by visiting:
   `http://localhost:8000/livekit/token?room=my-room&identity=test-user`

4. To actually test the voice call, open the LiveKit Console in your browser (LiveKit Cloud dashboard -> Agents -> Playground), or build a simple React frontend using `@livekit/components-react`, and connect to the room. The agent will greet you and you can start talking!
