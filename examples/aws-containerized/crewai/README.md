# Agent Kernel running CrewAI based agents in AWS Containered (ECS)

This package contains a demo of Agent Kernel running agents built with CrewAI, running them in a containered configuration using AWS ECS.

## Deployed Resources

This demo deploys the following AWS resources:

- AWS ECS running the Agent Kernel implementation.
- API Gateway endpoint for the ECS service.

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
    The service started with the placeholder, so force a new deployment to pick the key up:
    `aws ecs update-service --cluster <prefix> --service <prefix>-service --force-new-deployment`.
