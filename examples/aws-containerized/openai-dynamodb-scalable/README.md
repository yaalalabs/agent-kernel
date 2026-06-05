# OpenAI Agents on ECS — Scalable (SQS Queue Mode)

Agent Kernel running OpenAI Agents SDK agents on AWS ECS in **REST Sync queue mode**,
using SQS queues to decouple the HTTP request from agent processing and DynamoDB as
both agent memory (session store) and the response store.

## Architecture

```
Client
  │  POST /api/v1/chat
  ▼
API Gateway → ALB
  ▼
REST Service ECS task  ──── sends to ──►  Input SQS Queue
  │ (Thread 1: FastAPI)                        │
  │ (Thread 2: output-queue poller)            ▼
  │                                     Agent Runner ECS task
  │                                       (polls Input Queue,
  │                                        runs agent,
  │                                        sends to Output Queue)
  │                                            │
  │                                            ▼
  │                                     Output SQS Queue
  │                                            │
  │◄─── Thread 2 writes ───────────────────────┘
  │     to DynamoDB Response Store
  │
  └─── Thread 1 reads from DynamoDB Response Store
       and returns response to client
```

Two Docker images are built:

| Image | Source | Role |
|-------|--------|------|
| `dist-rest-service/` | `app_rest_service.py` | FastAPI API + output-queue poller |
| `dist-agent-runner/` | `app_agent_runner.py` | Input-queue consumer, runs the agent |

## Deployed Resources

- API Gateway (HTTP) + ALB → REST Service ECS task
- REST Service ECS service (Thread 1 + Thread 2)
- Agent Runner ECS service (separate Fargate task, no ALB)
- Input SQS FIFO Queue
- Output SQS FIFO Queue
- DynamoDB Response Store (TTL-enabled, temporary response buffer)
- DynamoDB Session Store (agent memory)

## Prerequisites

- AWS CLI configured with appropriate credentials
- Terraform `>= 1.9.5`
- `uv` Python package manager

## Deployment

1. Set environment variables:
   ```bash
   export TF_VAR_openai_api_key=<OPENAI_API_KEY>
   export TF_VAR_vpc_id=<VPC_ID>
   export TF_VAR_private_subnet_ids='["subnet-xxx","subnet-yyy"]'
   ```

2. Build and deploy:
   ```bash
   cd deploy && ./deploy.sh          # from PyPI
   cd deploy && ./deploy.sh local    # from local ak-py build
   ```

## Testing

```bash
curl -X POST <agent_invoke_url> \
  -H "Content-Type: application/json" \
  -d '{"prompt": "What is 12 * 9?", "session_id": "test-1"}'
```

The request blocks on the same HTTP connection until the Agent Runner
finishes processing and the response is available in DynamoDB.
