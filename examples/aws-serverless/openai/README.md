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

1. Navigate to the deployment directory and run the deployment script:
    ```bash
    cd deploy && ./deploy.sh #./deploy.sh local if dependencies are built locally
    ```

2. Overwrite the `REPLACE_ME` placeholder Terraform created with your key, where `<prefix>` is `prefix`
   in `deploy/terraform.tfvars` (see [Secrets from SSM Parameter Store](#secrets-from-ssm-parameter-store)).
   The agent runner reads it when an execution environment starts, so do this before the first request:
    ```bash
    aws ssm put-parameter --name "/ak/<prefix>/openai_api_key" \
        --type SecureString --value "$OPENAI_API_KEY" --overwrite
    ```

## Secrets from SSM Parameter Store

The deployment sets `ssm_enabled = true`, which grants the request handler, agent runner and response
handler Lambdas `ssm:GetParameter` (and nothing else) on `/ak/<prefix>/*` and injects
`AK_SECRET__PREFIX` into them (the request and response handlers need it only for messaging-integration
credentials, which this example has none of). `config.yaml` declares `secret.provider.type: aws_ssm`, and
`lambda_agent_runner.py` resolves the key at startup:

```python
set_default_openai_key(SecretManager.current().get("OPENAI_API_KEY"))
```

- **Resolution order:** a set, non-empty `OPENAI_API_KEY` environment variable still wins (handy
  for local runs); the deployment does not inject one, so on Lambda the key comes from SSM.
- **Naming:** the key is the SDK's own variable name, lowercased under the deployment prefix —
  `OPENAI_API_KEY` → `/ak/<prefix>/openai_api_key`.
- **Terraform creates the parameter, not its value.** `ssm_secret_keys = ["OPENAI_API_KEY"]` makes the
  module create a `SecureString` (AWS-managed `alias/aws/ssm` key) holding `REPLACE_ME`, and its
  `ignore_changes` keeps later applies from writing that back over your key. The provider still reads the
  parameter on every refresh, so after the next plan the real value is also in Terraform state: keep the
  state backend encrypted and access-restricted. A parameter that already exists makes the create fail —
  import it instead: `terraform import 'module.serverless_agents.aws_ssm_parameter.secret_placeholder["OPENAI_API_KEY"]' /ak/<prefix>/openai_api_key`.
- **Rotation:** overwrite the parameter with `aws ssm put-parameter ... --overwrite`. The key is
  handed to the SDK once, when the agent runner starts, so new execution environments pick up the
  new value while warm ones keep the old one until Lambda recycles them. To switch over
  immediately, update the agent runner function's configuration (for example its description) to
  force fresh environments.
