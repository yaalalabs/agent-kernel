# Agent Kernel running OpenAI Agents SDK with Authentication in AWS Serverless (Lambda)

This package contains a demo of Agent Kernel running agents built with OpenAI Agents SDK with authentication support, running them in a serverless configuration using AWS Lambda.

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

2. Get the VPC ID and private subnet IDs from the openai deployment:
    ```bash
    cd ../openai/deploy && terraform output vpc_id
    cd ../openai/deploy && terraform output private_subnet_ids
    ```

3. Configure environment variables:
    ```bash
    export TF_VAR_openai_api_key=<OPENAI_API_KEY>
    export TF_VAR_vpc_id=<VPC_ID_FROM_OPENAI>
    export TF_VAR_private_subnet_ids='["<SUBNET_ID_1>", "<SUBNET_ID_2>"]'
    ```

4. Navigate to the deployment directory and run the deployment script:
    ```bash
    cd deploy && ./deploy.sh #./deploy.sh local if dependencies are built locally
    ```
