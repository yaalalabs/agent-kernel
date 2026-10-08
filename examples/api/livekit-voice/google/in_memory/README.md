# Agent Kernel Realtime Voice (Google Gemini In-Memory)

This example demonstrates Agent Kernel's `REALTIME` execution pipeline for voice over WebRTC using LiveKit, powered by the **Google Gemini Live API**.

This is the absolute simplest way to test LiveKit voice on your local machine. Because it uses the `in_memory` queue transport, both the LiveKit Edge Gateway (the Front Door) and the Agent Runner (the Brain) run internally as threads inside a single Python process. No Docker, SQS, or Kafka required!

## Quickstart

### 1. Build and Setup
Configure your environment variables. You will need your Google Gemini API key and your LiveKit project credentials.
```bash
# Install dependencies
./build.sh

# Set credentials
export GEMINI_API_KEY="..."
export AK_LIVEKIT__URL="wss://your-project.livekit.cloud"
export AK_LIVEKIT__API_KEY="..."
export AK_LIVEKIT__API_SECRET="..."
```

### 2. Run the Server
Because this is an in-memory setup, you only need one terminal window!
```bash
python server.py
```

That's it! Connect to `room_01` in your LiveKit Sandbox dashboard and speak. The `IOHandler` will automatically spin up the `AgentRunner` in the background to seamlessly process the audio chunks.
