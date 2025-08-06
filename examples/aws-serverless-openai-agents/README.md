# Agent Kernel running OpenAI Agent SDK Agents

This package contains a demo of Agent Kernel running agents built with OpenAI Agents SDK. Users may
interact with agents via the Agent Kernel Lambda Implementation.

## Deployed Resources

This demo deploys the following AWS resources:

- AWS Lambda function running the Agent Kernel implementation
- API Gateway endpoint for the Lambda function

## Prerequisites

- AWS CLI configured with appropriate credentials
- Terraform (`1.9.5` or higher) installed

## Deployment Steps

1. Configure environment variables:
    ```bash
    export TF_VAR_openai_api_key=<OPENAI_API_KEY>
    ```

2. Navigate to deployment directory and run deployment script:
    ```bash
    cd deploy && ./deploy.sh
    ```