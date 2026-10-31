# Agent Kernel — Multimodal with Redis Attachment Storage on AWS Lambda

This example demonstrates how to use Agent Kernel's `RedisStorageDriver` to store and retrieve multimodal attachments (images, PDFs, etc.) in Redis — preventing session cache bloat.

## Deployed Resources

This demo deploys the following AWS resources:

- AWS Lambda function running the Agent Kernel implementation.
- API Gateway endpoint for the Lambda function.
- Redis (ElastiCache) cluster for multimodal attachment storage (set `create_redis_cluster = true` in `main.tf`, or configure an existing Redis URL in `config.yaml`).

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

## Config options (`config.yaml`)

```yaml
multimodal:
  enabled: true
  storage_type: redis
  redis:
    url: "redis://your-redis-host:6379"
    prefix: "ak:mm:redis:"       # all Redis keys are prefixed with this
```

The `url` can be overridden at runtime via the environment variable:
```bash
export AK_MULTIMODAL__REDIS__URL="redis://your-redis-host:6379"
```

## Running the Integration Test

After deployment, run the test against the deployed endpoint:

```bash
export AK_TEST_ENDPOINT=<API_GATEWAY_URL>
export OPENAI_API_KEY=<OPENAI_API_KEY>
uv run pytest redis_test.py -v -s
```

The test sends an image, verifies the agent describes it, then sends a follow-up without the image to verify Redis retrieval works.
