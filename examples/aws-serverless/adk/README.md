# Agent Kernel running Google ADK based agents in AWS Serverless (Lambda)

This package contains a demo of Agent Kernel running agents built with Google ADK, running them in a serverless configuration using AWS Lambda.

## Deployed Resources

This demo deploys the following AWS resources:

- AWS Lambda function running the Agent Kernel implementation.
- API Gateway endpoint for the Lambda function.

## Prerequisites

- AWS CLI configured with appropriate credentials.
- Terraform (`1.9.5` or higher) installed.

## Deployment Steps

1. Configure environment variables:
    ```bash
    export TF_VAR_gemini_api_key=<GEMINI_API_KEY>
    ```

2. Navigate to the deployment directory and run the deployment script:
    ```bash
    cd deploy && ./deploy.sh #./deploy.sh local if dependencies are built locally
    ```
