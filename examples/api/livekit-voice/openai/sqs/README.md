# Agent Kernel Realtime Voice over AWS SQS (LiveKit)

This package demonstrates Agent Kernel's scalable, containerized architecture running in **`REALTIME` execution mode** for voice over WebRTC. It uses LiveKit as the frontend voice gateway and AWS SQS as the backend message broker.

```
LiveKit WebRTC → ECSIOHandler → Input SQS Queue → ECSAgentRunner → Output SQS Queue → ECSIOHandler → LiveKit WebRTC
```

Because this is designed for production AWS deployments (AWS ECS), the pipeline is strictly separated into two physical files (`app_livekit_io.py` and `app_agent_runner.py`). Each file is meant to be built into its own Docker image and run as a completely independent Cloud Server (ECS Task) with its own security groups and scaling rules.

## Architecture Overview

- **REST/IO Service ECS Task** (`app_livekit_io.py`, started via `ECSIOHandler.run()`):
  - Acts as the "Front Door".
  - Connects to LiveKit, catches user audio via WebRTC, and throws the audio chunks onto the Input SQS Queue. 
  - Never runs the AI Agent itself.
  - Simultaneously polls the Output SQS Queue to catch the AI's response audio and streams it back to the LiveKit user.
- **Agent Runner ECS Task** (`app_agent_runner.py`, started via `ECSAgentRunner.run()`):
  - Acts as the "Brain".
  - Heavily locked down in a private AWS subnet.
  - Polls the Input SQS Queue for user audio chunks.
  - Maintains a persistent WebSocket connection to OpenAI for the duration of the phone call.
  - Pushes the AI's audio response chunks to the Output SQS Queue.
- **SQS Queues**: FIFO input and output queues (configured in `config.yaml`).


## Deployment & Testing


### Production AWS Deployment
1. Ensure you have your `OPENAI_API_KEY`, `AK_LIVEKIT__URL`, `AK_LIVEKIT__API_KEY`, and `AK_LIVEKIT__API_SECRET` set in your environment.
2. Use the Terraform modules in `ak-deployment/aws/containerized` to provision the real SQS queues and spin up the two separate ECS tasks!
