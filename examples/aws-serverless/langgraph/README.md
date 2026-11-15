# Agent Kernel running LangGraph based agents in AWS Serverless (Lambda)

This package contains a demo of Agent Kernel running agents built with LangGraph, running them in a serverless configuration using AWS Lambda.

## Deployed Resources

This demo deploys the following AWS resources:

- AWS Lambda function running the Agent Kernel implementation.
- API Gateway endpoint for the Lambda function.
- Redis Cluster: Session storage (shared with openai example)
- VPC: Private networking for Lambda functions (shared with openai example)

## Prerequisites

- AWS CLI configured with appropriate credentials.
- Terraform (`1.9.5` or higher) installed.
- The openai example must be deployed first to create the shared Redis cluster and VPC resources

## Deployment Steps

1. Deploy the openai example first to create the shared infrastructure:
    ```bash
    cd ../openai/deploy && ./deploy.sh
    ```

2. Get the VPC ID, private subnet IDs, and request handler security group ID from the openai deployment:
    ```bash
    cd ../openai/deploy && terraform output vpc_id
    cd ../openai/deploy && terraform output private_subnet_ids
    cd ../openai/deploy && terraform output request_handler_security_group_id
    ```

3. Store the OpenAI API key in SSM Parameter Store (`<prefix>` is `prefix` in `deploy/terraform.tfvars`) and configure the deployment:
    ```bash
    aws ssm put-parameter --name "/ak/<prefix>/openai_api_key" \
        --type SecureString --value "$OPENAI_API_KEY" --overwrite
    export TF_VAR_vpc_id=<VPC_ID_FROM_OPENAI>
    export TF_VAR_private_subnet_ids='["<SUBNET_ID_1>", "<SUBNET_ID_2>"]'
    export TF_VAR_request_handler_security_group_id=<SG_FROM_OPENAI> # optional, reuses the openai deployment's security group
    ```
    The deployment sets `ssm_enabled = true` and `config.yaml` selects the `aws_ssm` secret provider, so the app reads the key from SSM at startup; no secret passes through Terraform.

4. Navigate to the deployment directory and run the deployment script:
    ```bash
    cd deploy && ./deploy.sh #./deploy.sh local if dependencies are built locally
    ```
