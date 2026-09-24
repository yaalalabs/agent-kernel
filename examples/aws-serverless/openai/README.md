# Agent Kernel running OpenAI Agents SDK based agents in AWS Serverless (Lambda)

This package contains a demo of Agent Kernel running agents built with OpenAI Agents SDK, running them in a serverless configuration using AWS Lambda, using queue-mode's three-Lambda architecture (request handler, agent runner, response handler).

This is also the base deployment for the weekly integration test pipeline: the other `aws-serverless` weekly examples reuse the VPC, private subnets, and all three per-tier Lambda security groups this example creates, instead of each creating their own (see `docs/specs/716-reuse-sg-in-integration-test-pipeline`).

## Deployed Resources

This demo deploys the following AWS resources:

- **Lambda functions**: request handler (API Gateway ingress), agent runner (runs the agents), response handler (writes completed responses to the response store) — each built and pushed as a container image by Terraform itself.
- **SQS queues**: input and output queues connecting the three Lambdas.
- **API Gateway** endpoint for the request handler, plus the custom `/app`/`/app_info` routes.
- **Redis cluster**: session memory and response store.

## Prerequisites

- AWS CLI configured with appropriate credentials.
- Terraform (`1.9.5` or higher) installed.

## Deployment Steps

1. Store the OpenAI API key in SSM Parameter Store, where `<prefix>` is `prefix` in
   `deploy/terraform.tfvars` (see [Secrets from SSM Parameter Store](#secrets-from-ssm-parameter-store)).
   The key never passes through Terraform:
    ```bash
    aws ssm put-parameter --name "/ak/<prefix>/openai_api_key" \
        --type SecureString --value "$OPENAI_API_KEY" --overwrite
    ```

2. Navigate to the deployment directory and run the deployment script:
    ```bash
    cd deploy && ./deploy.sh #./deploy.sh local if dependencies are built locally
    ```

## Secrets from SSM Parameter Store

The deployment sets `ssm_enabled = true`, which grants every Lambda role `ssm:GetParameter` (and
nothing else) on `/ak/<prefix>/*` and injects `AK_SECRET__PREFIX`. `config.yaml` declares
`secret.provider.type: aws_ssm`, and `lambda_agent_runner.py` resolves the key at startup:

```python
set_default_openai_key(SecretManager.current().get("OPENAI_API_KEY"))
```

- **Resolution order:** a set, non-empty `OPENAI_API_KEY` environment variable still wins (handy
  for local runs); the deployment does not inject one, so on Lambda the key comes from SSM.
- **Naming:** the key is the SDK's own variable name, lowercased under the deployment prefix —
  `OPENAI_API_KEY` → `/ak/<prefix>/openai_api_key`.
- **Terraform does not create the parameter.** Create it as a `SecureString` with the AWS-managed
  `alias/aws/ssm` key, as shown above.
- **Rotation:** overwrite the parameter with `aws ssm put-parameter ... --overwrite`. The key is
  handed to the SDK once, when the agent runner starts, so new execution environments pick up the
  new value while warm ones keep the old one until Lambda recycles them. To switch over
  immediately, update the agent runner function's configuration (for example its description) to
  force fresh environments.
