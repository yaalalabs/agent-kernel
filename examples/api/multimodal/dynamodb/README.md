# DynamoDB Multimodal Example

This example demonstrates how to use Agent Kernel's `DynamoDBStorageDriver` to store and retrieve multimodal attachments (images, PDFs, etc.) in AWS DynamoDB — preventing session cache bloat.

## Files

| File | Purpose |
|---|---|
| `lambda.py` | AWS Lambda REST API server — the clean example you can deploy and learn from |
| `dynamodb_test.py` | Automated pytest — runs nightly in CI |
| `test_image.webp` | Test image (elephant with red dust) |

## Prerequisites

1. **AWS Account** with DynamoDB access
2. **AWS CLI** configured via SSO:
   ```bash
   aws configure sso
   ```
3. **DynamoDB Table** — deployment automatically creates the `mm-attachments` table for you when running `./deploy.sh local`. If doing custom usage outside of deployment:
   ```bash
   aws dynamodb create-table \
       --table-name AgentKernelMultimodalTable \
       --attribute-definitions \
           AttributeName=session_id,AttributeType=S \
           AttributeName=attachment_id,AttributeType=S \
       --key-schema \
           AttributeName=session_id,KeyType=HASH \
           AttributeName=attachment_id,KeyType=RANGE \
       --billing-mode PAY_PER_REQUEST \
       --profile your-aws-profile-name
   ```

## Deployment Steps

1. Store the OpenAI API key in SSM Parameter Store, where `<prefix>` is `prefix` in `deploy/terraform.tfvars`:
    ```bash
    aws ssm put-parameter --name "/ak/<prefix>/openai_api_key" \
        --type SecureString --value "$OPENAI_API_KEY" --overwrite
    ```
    The deployment sets `ssm_enabled = true` and `config.yaml` selects the `aws_ssm` secret provider, so the app reads the key from SSM at startup; no secret passes through Terraform.

2. Navigate to the deployment directory and run the deployment script:
    ```bash
    cd deploy && ./deploy.sh
    # or ./deploy.sh local if building from local source
    ```

## Config options (`config.yaml`)

```yaml
multimodal:
  enabled: true
  storage_type: dynamodb
  dynamodb:
    table_name: "mm-attachments"
```

## Running the Integration Test

After deployment, run the test against the deployed endpoint:

```bash
export AK_TEST_ENDPOINT=<API_GATEWAY_URL>
export OPENAI_API_KEY=<OPENAI_API_KEY>
uv run pytest dynamodb_test.py -v -s
```

