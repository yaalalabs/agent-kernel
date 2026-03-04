# DynamoDB Multimodal Example

This example demonstrates how to use Agent Kernel's `DynamoDBStorageDriver` to store and retrieve multimodal attachments (images, PDFs, etc.) in AWS DynamoDB — preventing session cache bloat.

## Files

| File | Purpose |
|---|---|
| `app.py` | REST API server — the clean example you can run and learn from |
| `dynamodb_test.py` | Automated pytest — runs nightly in CI |
| `test_image.webp` | Test image (elephant with red dust) |

## Prerequisites

1. **AWS Account** with DynamoDB access
2. **AWS CLI** configured via SSO:
   ```bash
   aws configure sso
   ```
3. **DynamoDB Table** — the test creates and deletes its own table automatically. For the `app.py` example, create one manually:
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

## Running the Example

```bash
# Login to AWS
aws sso login --profile your-aws-profile-name

# Install dependencies
./build.sh local

# Set environment and run
export AWS_PROFILE="your-aws-profile name"
export AWS_REGION="your-aws-region"
export OPENAI_API_KEY="your-key"
uv run app.py
```

The server starts at `http://localhost:8000`. Send images via the `/api/v1/chat` endpoint.

