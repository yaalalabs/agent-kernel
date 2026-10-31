# Agent Kernel running OpenAI Agents SDK based agents in AWS Lambda with AWS DynamoDB as agent memory

This package contains a demo of Agent Kernel running agents built with OpenAI Agents SDK, running them in a serverless configuration using AWS Lambda using AWS DynamoDB as agent memory

## Deployed Resources

This demo deploys the following AWS resources:

- AWS Lambda function running the Agent Kernel implementation.
- API Gateway endpoint for the Lambda function.
- Configuration changes to enable dynamodb as agent memory (Refer to `config.yaml` for details).

## Prerequisites

- AWS CLI configured with appropriate credentials.
- Terraform (`1.9.5` or higher) installed.

## Deployment Steps

1. Navigate to the deployment directory and run the deployment script:
    ```bash
    cd deploy && ./deploy.sh #./deploy.sh local if dependencies are built locally
    ```

    Terraform creates `/ak/<prefix>/openai_api_key` holding the placeholder `REPLACE_ME` (`ssm_enabled` and
    `ssm_secret_keys` in `deploy/main.tf`; `config.yaml` selects the `aws_ssm` secret provider). Overwrite it
    with your key, where `<prefix>` is `prefix` in `deploy/terraform.tfvars`:
    ```bash
    aws ssm put-parameter --name "/ak/<prefix>/openai_api_key" \
        --type SecureString --value "$OPENAI_API_KEY" --overwrite
    ```
    A Lambda execution environment reads the key when it starts, so set it before the first request.
