# Agent Kernel running OpenAI Agents SDK based agents in AWS Lambda with AWS DynamoDB as agent memory

This package contains a demo of Agent Kernel running agents built with OpenAI Agents SDK, running them in a serverless configuration using AWS Lambda using AWS DynamoDB as agent memory

## Deployed Resources

This demo deploys the following AWS resources:

- AWS Lambda function running the Agent Kernel implementation.
- API Gateway endpoint for the Lambda function.
- Configuration changes to enable dynamodb as agent memory (Refer to `config.yaml` for details).
- A DynamoDB table for conversation threads, via `create_dynamodb_thread_table = true` in `deploy/main.tf`.
  As with session memory, the backend is declared by the application (`thread.type: dynamodb` in
  `config.yaml`); the Terraform flag provisions the table and injects its generated name as
  `AK_THREAD__DYNAMODB__TABLE_NAME`. Note that enabling threads makes `user_id` required on every chat
  request (see `lambda_test.py`).

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
