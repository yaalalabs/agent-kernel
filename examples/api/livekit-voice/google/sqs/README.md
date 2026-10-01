# Agent Kernel Realtime Voice over AWS SQS (LiveKit + Gemini Live)

This package demonstrates Agent Kernel's scalable, containerized architecture running in **`REALTIME` execution mode** for voice over WebRTC. It uses LiveKit as the frontend voice gateway, **Google Gemini Live** as the realtime model, and AWS SQS as the backend message broker.

```
LiveKit WebRTC → IOHandler → Input SQS Queue → ECSAgentRunner → Output SQS Queue → IOHandler → LiveKit WebRTC
```

Because this is designed for production AWS deployments (AWS ECS), the pipeline is strictly separated into two physical files (`app_livekit_io.py` and `app_agent_runner.py`). Each file is meant to be built into its own Docker image and run as a completely independent Cloud Server (ECS Task) with its own security groups and scaling rules.

## Architecture Overview

- **REST/IO Service ECS Task** (`app_livekit_io.py`, started via `IOHandler.run()`):
  - Acts as the "Front Door".
  - Connects to LiveKit, catches user audio via WebRTC, and throws the audio chunks onto the Input SQS Queue.
  - Never runs the AI Agent itself.
  - Simultaneously polls the Output SQS Queue to catch the AI's response audio and streams it back to the LiveKit user.
- **Agent Runner ECS Task** (`app_agent_runner.py`, started via `ECSAgentRunner.run()`):
  - Acts as the "Brain".
  - Heavily locked down in a private AWS subnet.
  - Polls the Input SQS Queue for user audio chunks.
  - Maintains a persistent WebSocket connection to Google Gemini Live for the duration of the call.
  - Pushes the AI's audio response chunks to the Output SQS Queue.
- **SQS Queues**: FIFO input and output queues (configured in `config.yaml`).

The realtime model is pinned on the agent in `app_agent_runner.py` (`gemini-3.1-flash-live-preview`), and the LiveKit credential binding (`AK_LIVEKIT__*`) is injected by Terraform.

## Prerequisites

- An AWS account with credentials configured, plus Terraform and Docker.
- A LiveKit project (WebSocket URL, API key, API secret) from [LiveKit Cloud](https://cloud.livekit.io/).
- A Google **Gemini API key**.

## Deployment

The `livekit` and `adk` extras are not on PyPI yet, so build the local `agentkernel` wheel first, then deploy with `local` (which pulls it from `ak-py/dist`):

```bash
# 1. Build the local wheel (must be Python 3.12 to match the container image).
(cd ak-py && uv build --wheel)

# 2. Supply the deployment inputs (or put them in deploy/terraform.tfvars).
export TF_VAR_GOOGLE_API_KEY="..."
export TF_VAR_livekit_url="wss://your-project.livekit.cloud"
export TF_VAR_livekit_api_key="..."
export TF_VAR_livekit_api_secret="..."
export TF_VAR_vpc_id="vpc-..."
export TF_VAR_private_subnet_ids='["subnet-aaa","subnet-bbb"]'

# 3. Build the deployment packages and apply.
cd examples/api/livekit-voice/google/sqs
UV_PYTHON=3.12 ./deploy.sh local
```

> **Python version**: `deploy.sh` installs dependencies on the build host and copies them into a
> `python:3.12-slim` image, so the build interpreter must be 3.12. `UV_PYTHON=3.12` forces that even
> if your active venv is a different version; otherwise compiled wheels (e.g. `pydantic_core`) are
> built for the wrong ABI and the container fails at startup.

## Testing

1. Join LiveKit room `room_01` (mint a token for it, or use the LiveKit Agents Playground) and speak.
2. Watch the IO service logs for `LiveKit WebRTC connection established.` and the agent runner logs
   for the agent selection / tool execution.

## Realtime tuning

`config.yaml` exposes two `execution.realtime` knobs:

- `playback_lead_ms` (default `50`) — audio buffered ahead of playback at the edge. SQS adds more
  latency/jitter than in-process/Kafka/NATS, so the example raises it to smooth out choppy playback.
- `input_batch_ms` (default `100`) — mic audio batched per input-queue message; `0` passes every
  frame straight through (lower latency, many more messages).
