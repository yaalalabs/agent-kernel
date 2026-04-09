# Agent Kernel Scalable OpenAI Agents with AWS Serverless Architecture

This package demonstrates a scalable Agent Kernel implementation running OpenAI Agents SDK with authentication support, using AWS serverless architecture with queue-based processing.

## Architecture Overview

This deployment uses a scalable serverless architecture with the following components:

- **Request Handler Lambda**: Receives HTTP requests and queues them for processing
- **Agent Runner Lambda**: Processes agent requests from the input queue
- **Response Handler Lambda**: Processes completed responses from the output queue
- **SQS Queues**: Input and output queues for asynchronous processing
- **Redis Cluster**: For agent memory and response storage
- **API Gateway**: REST API endpoint with authentication
- **WebSocket API**: For real-time response delivery (async mode)

## Deployed Resources

This demo deploys the following AWS resources:

- **Lambda Functions**:
  - Request Handler: Handles incoming HTTP requests
  - Agent Runner: Executes agent logic asynchronously  
  - Response Handler: Processes and stores responses
  - Authorizer: API Gateway authentication
- **SQS Queues**: Input and output queues with dead letter queues
- **Redis Cluster**: For session storage and response caching
- **API Gateway**: REST API with custom endpoints
- **VPC**: Private networking for Lambda functions
- **CloudWatch**: Logging and monitoring

## Execution Mode

This example uses `rest_async` execution mode, which provides:
- Asynchronous processing for better scalability
- Queue-based architecture for handling load spikes
- Separate scaling for request handling and agent processing
- Response storage for retrieving results

## Prerequisites

- AWS CLI configured with appropriate credentials
- Terraform (`1.9.5` or higher) installed
- Docker installed (for building container images)
- UV package manager installed

## Deployment Steps

1. Configure environment variables:
    ```bash
    export TF_VAR_openai_api_key=<OPENAI_API_KEY>
    ```

2. Build the deployment packages:
    ```bash
    ./build.sh  # or ./build.sh local for local development
    ```

3. Navigate to the deployment directory and run the deployment script:
    ```bash
    cd deploy && ./deploy.sh
    ```

## Testing the Deployment

After deployment, you can test the scalable agent:

### REST_SYNC Mode:
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

### REST_ASYNC Mode

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
- Redis cluster performance
- API Gateway request metrics
