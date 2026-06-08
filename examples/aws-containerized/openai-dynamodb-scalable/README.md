# Agent Kernel Scalable OpenAI Agents with AWS ECS Architecture

This package demonstrates a scalable Agent Kernel implementation running OpenAI Agents SDK on AWS ECS with queue-based processing.

## Architecture Overview

This deployment uses a scalable containerized architecture with the following components:

- **REST Service ECS Task**: Receives HTTP requests (Thread 1) and processes output queue messages (Thread 2)
- **Agent Runner ECS Task**: Processes agent requests from the input queue
- **SQS Queues**: Input and output queues for asynchronous processing
- **DynamoDB Tables**: For session memory and response storage
- **API Gateway + ALB**: REST API endpoint routing to ECS services

## Deployed Resources

This demo deploys the following AWS resources:

- **ECS Services**:
  - REST Service: FastAPI server + output queue poller (2 threads)
  - Agent Runner: Input queue consumer and agent executor
- **SQS Queues**: FIFO input and output queues
- **DynamoDB**: Session storage and response store tables
- **API Gateway + ALB**: HTTP API with VPC Link to Application Load Balancer
- **VPC**: Private networking for ECS tasks
- **CloudWatch**: Logging and monitoring

## Execution Mode

This example supports two queue modes configured via `queue_mode_type` in `deploy/main.tf`:

### REST_SYNC Mode (default)
```hcl
queue_mode_type = "sync"
```

Client request blocks until agent completes. Response returned on same HTTP connection.

### REST_ASYNC Mode (optional)
```hcl
queue_mode_type = "async"
```

Client request returns immediately with `request_id`. Client polls separate GET endpoint for result.

Both modes use the same 2-image architecture (REST Service + Agent Runner) with queue-based processing.

## Prerequisites

- AWS CLI configured with appropriate credentials
- Terraform (`1.9.5` or higher) installed
- Docker installed (for building container images)
- UV package manager installed

## Deployment Steps

1. Configure environment variables:
    ```bash
    export TF_VAR_openai_api_key=<OPENAI_API_KEY>
    export TF_VAR_vpc_id=<VPC_ID>
    export TF_VAR_private_subnet_ids='["subnet-xxx","subnet-yyy"]'
    export TF_VAR_product_alias="ak-oai-scl-ecs"
    export TF_VAR_env_alias="dev"
    export TF_VAR_module_name="scalable"
    export TF_VAR_region="us-east-1"
    ```

2. Build the deployment packages:
    ```bash
    ./build.sh
    ```

3. Navigate to the deployment directory and run the deployment script:
    ```bash
    cd deploy && ./deploy.sh
    ```

## Testing the Deployment

After deployment, you can test the scalable agent:

### REST_SYNC Mode (default):

**Submit request (blocks until complete)**:
```bash
curl -X POST https://your-api-gateway-url/agents/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "What is 12 * 9?",
    "session_id": "test-1",
    "agent": "math"
  }'
```

Response:
```json
{
  "result": "108",
  "session_id": "test-1"
}
```

### REST_ASYNC Mode (optional):

**Step 1 - Submit request (returns immediately)**:
```bash
curl -X POST https://your-api-gateway-url/agents/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "What is 12 * 9?",
    "session_id": "test-1",
    "agent": "math"
  }'
```

Response:
```json
{
  "status": "ACCEPTED",
  "request_id": "9fce843f-f8bb-4818-bf35-5167247e17c8",
  "session_id": "test-1"
}
```

**Step 2 - Poll for result**:
```bash
curl -X GET https://your-api-gateway-url/agents/api/v1/chat/test-1?request_id=9fce843f-f8bb-4818-bf35-5167247e17c8
```

Response (while processing or if not found):
```json
{
  "error": "NOT_FOUND",
  "message": "No response message found for request_id '9fce843f-f8bb-4818-bf35-5167247e17c8'. The message may be unavailable. Please try again.",
  "request_id": "9fce843f-f8bb-4818-bf35-5167247e17c8",
  "session_id": "test-1"
}
```

Response (when complete):
```json
{
  "result": "108",
  "session_id": "test-1"
}
```

**Note**: The client should retry polling with exponential backoff when receiving NOT_FOUND. This status means the response isn't in DynamoDB yet (still processing) or the request_id is invalid.

## Architecture Details

### Two-Image Pattern

| Image | Source | Role |
|-------|--------|------|
| REST Service | `app_rest_service.py` | Thread 1: FastAPI API server<br/>Thread 2: Output queue poller → DynamoDB |
| Agent Runner | `app_agent_runner.py` | Input queue consumer → Agent executor → Output queue |

### Request Flow

**REST_SYNC Mode:**
1. Client → API Gateway → ALB → REST Service (Thread 1)
2. REST Service → Input SQS Queue (enqueue request)
3. Agent Runner polls Input Queue → Executes agent → Sends to Output Queue
4. REST Service Thread 2 polls Output Queue → Writes to DynamoDB Response Store
5. REST Service Thread 1 polls DynamoDB → Returns response to client

**REST_ASYNC Mode:**
1. Client → API Gateway → ALB → REST Service (Thread 1)
2. REST Service → Input SQS Queue → Returns `request_id` immediately
3. Agent Runner polls Input Queue → Executes agent → Sends to Output Queue
4. REST Service Thread 2 polls Output Queue → Writes to DynamoDB Response Store
5. Client polls GET endpoint → REST Service reads DynamoDB → Returns response

### CMD Override

The ECR module (`terraform-aws-modules/lambda/aws//modules/docker-build`) is Lambda-oriented and automatically injects:
```dockerfile
CMD ["python","-c","from app import runner; runner()"]
```

This is overridden at ECS task definition level using:
- `ecs_container_command = ["python", "app_rest_service.py"]`
- `agent_runner_command = ["python", "app_agent_runner.py"]`

See [COMMAND_OVERRIDE.md](../../ak-deployment/ak-aws/containerized/COMMAND_OVERRIDE.md) for details.

## Monitoring and Scaling

The architecture automatically scales based on:
- **REST Service**: Scales with ALB target group metrics
- **Agent Runner**: Scales based on SQS queue depth

Monitor through CloudWatch:
- ECS task metrics and logs
- SQS queue depth and processing rates
- DynamoDB read/write metrics
- API Gateway and ALB request metrics

## Troubleshooting

### ModuleNotFoundError: No module named 'app'

Old Docker images cached in ECR. Redeploy:
```bash
cd deploy && ./deploy.sh
```

### Service Not Starting

Check CloudWatch logs:
```bash
# REST Service
aws logs tail /ecs/<product>-<env>-<module> --follow

# Agent Runner
aws logs tail /ecs/<product>-<env>-<module>-agent-runner --follow
```

### Debug Response Store

Inspect or clear DynamoDB response store:
```bash
python debug_response_store.py --list
python debug_response_store.py --clear
```

## Related Documentation

- **[ROOT_CAUSE_ANALYSIS.md](ROOT_CAUSE_ANALYSIS.md)** - Deep dive into CMD override issue
- **[COMMAND_OVERRIDE.md](../../ak-deployment/ak-aws/containerized/COMMAND_OVERRIDE.md)** - Command override usage
- **[Serverless Reference](../aws-serverless/scalable-openai/)** - Lambda implementation
- **[Queue Mode Guide](../../docs/queue-mode-guide.md)** - Queue architecture details
   ```

3. Build and deploy:
   ```bash
   cd deploy && ./deploy.sh          # from PyPI
   cd deploy && ./deploy.sh local    # from local ak-py build
   ```

**Note:** The deploy script builds two separate Docker images:
- `dist-rest-service/` containing `app_rest_service.py` (FastAPI + output queue poller)
- `dist-agent-runner/` containing `app_agent_runner.py` (input queue consumer)

If you encounter "ModuleNotFoundError: No module named 'app'" errors, old Docker images
may be cached in ECR. Run `./clean.sh` and redeploy to rebuild from scratch.

## Testing

### REST_SYNC Mode (Default)

Request blocks until agent completes:

```bash
curl -X POST <agent_invoke_url>/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "What is 12 * 9?",
    "session_id": "test-1",
    "agent": "math"
  }'
```

The request blocks on the same HTTP connection until the Agent Runner
finishes processing and the response is available in DynamoDB.

### REST_ASYNC Mode

**Step 1:** Submit request (returns immediately):

```bash
curl -X POST <agent_invoke_url>/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "What is 12 * 9?",
    "session_id": "test-1",
    "agent": "math"
  }'
```

Response:
```json
{
  "status": "ACCEPTED",
  "request_id": "9fce843f-f8bb-4818-bf35-5167247e17c8",
  "session_id": "test-1"
}
```

**Step 2:** Poll for result:

```bash
curl -X GET <agent_invoke_url>/api/v1/chat/test-1?request_id=9fce843f-f8bb-4818-bf35-5167247e17c8
```

Returns `{"status": "PENDING", ...}` while processing, then the agent response.

**To enable REST_ASYNC mode:** Set `AK_EXECUTION__MODE=rest_async` in `deploy/main.tf` environment variables.
