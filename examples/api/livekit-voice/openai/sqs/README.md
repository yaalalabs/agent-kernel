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
1. Pass the LiveKit URL to Terraform and deploy from `deploy/`:
    ```bash
    export TF_VAR_livekit_url="wss://your-project.livekit.cloud"
    ./deploy.sh
    ```
   The deployment sets `ssm_enabled = true` and `ssm_secret_keys`, so Terraform creates the OpenAI key and the LiveKit
   API key and secret as SSM parameters holding `REPLACE_ME`; `config.yaml` selects the `aws_ssm` secret provider.

2. Overwrite the placeholders, where `<prefix>` is `prefix` in `deploy/terraform.tfvars`, then restart both services,
   which started with the placeholders:
    ```bash
    for pair in "openai_api_key=$OPENAI_API_KEY" "ak_livekit__api_key=$LIVEKIT_API_KEY" "ak_livekit__api_secret=$LIVEKIT_API_SECRET"; do
      aws ssm put-parameter --name "/ak/<prefix>/${pair%%=*}" --type SecureString --value "${pair#*=}" --overwrite
    done
    for service in <prefix>-service <prefix>-agent-runner; do
      aws ecs update-service --cluster <prefix> --service "$service" --force-new-deployment
    done
    ```
