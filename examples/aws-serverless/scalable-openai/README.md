# Agent Kernel Scalable OpenAI Agents with AWS Serverless Architecture

This package demonstrates a scalable Agent Kernel implementation running OpenAI Agents SDK on AWS serverless infrastructure with queue-based processing.

## Architecture Overview

This deployment uses a scalable serverless architecture with the following components:

- **Request Handler Lambda**: Receives HTTP requests and queues them for processing
- **Agent Runner Lambda**: Processes agent requests from the input queue (runs as a container image in ECR)
- **Response Handler Lambda**: Processes completed responses from the output queue
- **SQS Queues**: Input and output queues for asynchronous processing
- **DynamoDB Tables**: For session memory and response storage
- **API Gateway**: REST API endpoint with custom routes

## Deployed Resources

This demo deploys the following AWS resources:

- **Lambda Functions**:
  - Request Handler: Handles incoming HTTP requests (deployed from S3 ZIP)
  - Agent Runner: Executes agent logic asynchronously (deployed from ECR container image)
  - Response Handler: Processes and stores responses (deployed from S3 ZIP)
- **SQS Queues**: Input and output queues (DLQs disabled in this example)
- **DynamoDB**: Session storage and response store tables
- **API Gateway**: REST API with custom endpoints
- **VPC**: Private networking for Lambda functions
- **CloudWatch**: Logging and monitoring

## Deployment Package Types

Each Lambda uses an external artifact for deployment — no local Docker build of the main Lambda code happens during `terraform apply`:

| Lambda | Package Type | Artifact |
|--------|-------------|----------|
| Request Handler | `S3Zip` | ZIP uploaded to S3 |
| Agent Runner | `Image` | Container image pushed to ECR |
| Response Handler | `S3Zip` | ZIP uploaded to S3 |

The `deploy.sh` script handles building and uploading all three artifacts before running `terraform apply`.

## Execution Mode

This example defaults to `rest_sync` execution mode with queue mode enabled (`queue_mode = true`).

You can switch to `rest_async` by updating `deploy/main.tf`:

```hcl
execution_mode = "rest_async"
```

Both modes keep the scalable multi-Lambda architecture (`request_handler`, `agent_runner`, `response_handler`).

## Prerequisites

- AWS CLI configured with appropriate credentials
- Terraform (`1.9.5` or higher) installed
- Docker installed (for building the agent runner container image)
- UV package manager installed
- An S3 bucket for Lambda deployment packages (update `S3_BUCKET` in `deploy/deploy.sh`)
- An ECR repository for the agent runner image

## Deployment Steps

1. Configure environment variables:
    ```bash
    export TF_VAR_openai_api_key=<OPENAI_API_KEY>
    ```

2. Update `deploy/deploy.sh` with your S3 bucket name:
    ```bash
    S3_BUCKET=<your-s3-bucket-name>
    ```

3. Update `deploy/terraform.tfvars` with your S3 bucket and ECR repository details:
    ```hcl
    request_handler_lambda_package_s3 = {
      bucket = "<your-s3-bucket>"
      key    = "dist_request_handler.zip"
    }
    response_handler_lambda_package_s3 = {
      bucket = "<your-s3-bucket>"
      key    = "dist_response_handler.zip"
    }
    agent_runner_ecr_image_uri = "<account-id>.dkr.ecr.<region>.amazonaws.com/<repo-name>:latest"
    ```

4. Run the deployment script from the `deploy/` directory:
    ```bash
    cd deploy && ./deploy.sh  # ./deploy.sh local for local agentkernel build
    ```

    The script will:
    - Build and zip the request handler and response handler
    - Build the agent runner container image and push it to ECR
    - Upload ZIP packages to S3
    - Run `terraform apply`

## Testing the Deployment

After deployment, you can test the scalable agent:

### REST_SYNC Mode (default):
1. **Submit the request**:
   ```bash
   curl -X POST https://your-api-gateway-url/api/v1/chat \
     -H "Content-Type: application/json" \
     -d '{"prompt": "Hello, how are you?", "agent": "triage", "session_id": "user-123"}'
   ```

   Response:
   ```json
   {
     "result": "Agent response here",
     "session_id": "user-123"
   }
   ```

2. **Custom endpoints**:
   ```bash
   # Health check
   curl -X GET https://your-api-gateway-url/api/v1/app

   # App info
   curl -X POST https://your-api-gateway-url/api/v1/app_info \
     -H "Content-Type: application/json" \
     -d '{"query": "status"}'
   ```

### REST_ASYNC Mode (optional)

1. **Submit the request**:
   ```bash
   curl -X POST https://your-api-gateway-url/api/v1/chat \
     -H "Content-Type: application/json" \
     -d '{"prompt": "Hello, how are you?", "agent": "triage", "session_id": "user-123"}'
   ```

   Response:
   ```json
   {
     "status": "ACCEPTED",
     "request_id": "req-123"
   }
   ```

2. **Poll for the response**:
   ```bash
   curl -X GET https://your-api-gateway-url/api/v1/chat \
     -H "Content-Type: application/json" \
     -d '{"request_id": "req-123"}'
   ```

   Response:
   ```json
   {
     "result": "Agent response here",
     "session_id": "user-123"
   }
   ```

3. **Custom endpoints**:
   ```bash
   # Health check
   curl -X GET https://your-api-gateway-url/api/v1/app

   # App info
   curl -X POST https://your-api-gateway-url/api/v1/app_info \
     -H "Content-Type: application/json" \
     -d '{"query": "status"}'
   ```

## Monitoring and Scaling

The architecture automatically scales based on:
- **Request Handler**: Scales with API Gateway traffic
- **Agent Runner**: Scales based on SQS queue depth
- **Response Handler**: Scales based on output queue messages

Monitor through CloudWatch:
- Lambda function metrics and logs
- SQS queue depth and processing rates
- DynamoDB read/write metrics
- API Gateway request metrics
