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

1. Store the OpenAI API key in SSM Parameter Store, where `<prefix>` is `prefix` in `deploy/terraform.tfvars`:
    ```bash
    aws ssm put-parameter --name "/ak/<prefix>/openai_api_key" \
        --type SecureString --value "$OPENAI_API_KEY" --overwrite
    ```
    The deployment sets `ssm_enabled = true` and `config.yaml` selects the `aws_ssm` secret provider, so the app reads the key from SSM at startup; no secret passes through Terraform.

2. Navigate to the deployment directory and run the deployment script:
    ```bash
    cd deploy && ./deploy.sh #./deploy.sh local if dependencies are built locally
    ```
