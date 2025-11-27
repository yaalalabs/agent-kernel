# Agent Kernel running OpenAI Agents SDK based agents in AWS ECS with AWS DynamoDB as agent memory

This package contains a demo of Agent Kernel running agents built with OpenAI Agents SDK, running them in a containerized configuration on AWS ECS using AWS DynamoDB as agent memory

## Deployed Resources

This demo deploys the following AWS resources:

- Python application running the Agent Kernel implementation.
- API Gateway endpoint for the ECS service.
- Configuration changes to enable dynamodb as agent memory (Refer to `config.yaml` for details).

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
