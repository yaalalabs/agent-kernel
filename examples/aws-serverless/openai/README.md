# Agent Kernel running OpenAI Agents SDK based agents in AWS Serverless (Lambda)

This package contains a demo of Agent Kernel running agents built with OpenAI Agents SDK, running them in a serverless configuration using AWS Lambda, using queue-mode's three-Lambda architecture (request handler, agent runner, response handler).

This is also the base deployment for the weekly integration test pipeline: the other `aws-serverless` weekly examples reuse the VPC, private subnets, and all three per-tier Lambda security groups this example creates, instead of each creating their own (see `docs/specs/716-reuse-sg-in-integration-test-pipeline`).

## Deployed Resources

This demo deploys the following AWS resources:

- **Lambda functions**: request handler (API Gateway ingress), agent runner (runs the agents), response handler (writes completed responses to the response store) — each built and pushed as a container image by Terraform itself.
- **SQS queues**: input and output queues connecting the three Lambdas.
- **API Gateway** endpoint for the request handler, plus the custom `/app`/`/app_info` routes.
- **Redis cluster**: session memory and response store.

## Prerequisites

- AWS CLI configured with appropriate credentials.
- Terraform (`1.9.5` or higher) installed.

## Deployment Steps

1. Configure environment variables:
    ```bash
    export TF_VAR_openai_api_key=<OPENAI_API_KEY>
    ```

2. Navigate to the deployment directory and run the deployment script:
    ```bash
    cd deploy && ./deploy.sh #./deploy.sh local if dependencies are built locally
    ```
