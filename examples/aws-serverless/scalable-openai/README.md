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
- **Redis Cluster**: Session storage and response store (shared with openai example)
- **API Gateway**: REST API with custom endpoints
- **VPC**: Private networking for Lambda functions (shared with openai example)
- **CloudWatch**: Logging and monitoring

## Deployment Package Types

Each Lambda uses an external artifact for deployment — no local Docker build of the main Lambda code happens during `terraform apply`:

| Lambda | Package Type | Artifact |
|--------|-------------|----------|
| Request Handler | `S3Zip` | ZIP uploaded to S3 |
| Agent Runner | `Image` | Container image pushed to ECR |
| Response Handler | `S3Zip` | ZIP uploaded to S3 |

The `deploy.sh` script handles building and uploading all three artifacts before running `terraform apply`.

> **Bucket versioning is required for redeploys.** The request/response handlers use the external "bring-your-own bucket" option (`lambda_package_s3`). Terraform only redeploys a Lambda when its `s3_object_version` (or bucket/key) changes, and the key here is stable — so the bucket **must have S3 versioning enabled**. `deploy.sh` uploads each ZIP, captures the new object version, and passes it to Terraform (`-var`) automatically, so changed code redeploys the Lambda. On an unversioned bucket there is no version and the old code keeps running. (Deploying without `deploy.sh`? Set `version_id` in `terraform.tfvars` yourself.) See [issue #548](https://github.com/yaalalabs/agent-kernel/issues/548).

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
- The openai example must be deployed first to create the shared Redis cluster and VPC resources
- A **versioned** S3 bucket for Lambda deployment packages (update `S3_BUCKET` in `deploy/deploy.sh`) — versioning is required so code changes redeploy the Lambdas (see below)
- An ECR repository for the agent runner image

## Deployment Steps

1. Deploy the openai example first to create the shared infrastructure:
    ```bash
    cd ../openai/deploy && ./deploy.sh
    ```

2. Update `deploy/deploy.sh` with your S3 bucket name:
    ```bash
    S3_BUCKET=<your-s3-bucket-name>
    ```

3. Update `deploy/terraform.tfvars` with your (versioned) S3 bucket and ECR repository details:
    ```hcl
    request_handler_lambda_package_s3 = {
      bucket = "<your-versioned-s3-bucket>"
      key    = "dist_request_handler.zip"
    }
    response_handler_lambda_package_s3 = {
      bucket = "<your-versioned-s3-bucket>"
      key    = "dist_response_handler.zip"
    }
    agent_runner_ecr_image_uri = "<account-id>.dkr.ecr.<region>.amazonaws.com/<repo-name>:latest"
    ```

    The bucket **must have versioning enabled**. `deploy.sh` captures each uploaded object's version and passes it to Terraform as `version_id`, so you don't set it by hand. If you run `terraform apply` yourself (without `deploy.sh`), add `version_id` to each block — get it with:
    ```bash
    aws s3api head-object --bucket <your-bucket> --key dist_request_handler.zip --query VersionId --output text
    ```

4. Run the deployment script from the `deploy/` directory:
    ```bash
    cd deploy && ./deploy.sh  # ./deploy.sh local for local agentkernel build
    ```

    The script will:
    - Build and zip the request handler and response handler
    - Build the agent runner container image and push it to ECR
    - Upload the ZIPs to S3 and capture each object's version
    - Run `terraform apply`, passing the captured `version_id`s so changed code redeploys the Lambdas

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
- Redis cluster metrics
- API Gateway request metrics
