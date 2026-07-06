# Agent Kernel running OpenAI Agents SDK based agents in AWS ECS with AWS DynamoDB as agent memory

This package contains a demo of Agent Kernel running agents built with OpenAI Agents SDK, running them in a containerized configuration on AWS ECS using AWS DynamoDB as agent memory.

## Deployed Resources

This demo deploys the following AWS resources:

- Python application running the Agent Kernel implementation
- ECS Fargate service running the containerized application
- API Gateway endpoint for the ECS service
- DynamoDB table for agent memory
- Configuration changes to enable DynamoDB as agent memory (refer to `config.yaml` for details)

## Deployment Package Type

This example uses an **external ECR image** for deployment:

- **Package Type**: Pre-built container image in ECR
- **ECR Image URI**: Specified in `terraform.tfvars` as `ecr_image_uri`
- No local Docker image build happens during `terraform apply`

The `deploy/deploy.sh` script builds the Docker image, pushes it to ECR, and then runs `terraform apply` using the pushed image URI.

## Prerequisites

- AWS CLI configured with appropriate credentials
- Terraform (`1.9.5` or higher) installed
- Docker installed (for building the container image)
- UV package manager installed
- An ECR repository for the application image

## Deployment Steps

1. Configure environment variables:
    ```bash
    export TF_VAR_openai_api_key=<OPENAI_API_KEY>
    ```

2. Update `deploy/terraform.tfvars` with your ECR repository details:
    ```hcl
    ecr_image_uri = "<account-id>.dkr.ecr.<region>.amazonaws.com/<repo-name>:latest"
    ```

3. Run the deployment script from the `deploy/` directory:
    ```bash
    cd deploy && ./deploy.sh  # ./deploy.sh local for local agentkernel build
    ```

    The script will:
    - Build the application deployment package with dependencies
    - Build the Docker image with the deployment package
    - Push the image to the specified ECR repository
    - Run `terraform apply` using the external ECR image URI

## Alternative: Local Image Build

If you prefer to have Terraform build the image locally instead of using a pre-built ECR image, you can:

1. Set `ecr_image_uri = null` in `terraform.tfvars`
2. Set `package_path = "../dist"` in `deploy/main.tf`
3. The module will build and push the image from the local source during `terraform apply`

However, the default approach (using an external ECR image) is recommended for production deployments as it provides better control over the build and versioning process.
