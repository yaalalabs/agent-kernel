# Waste Sorting Assistant

An Agent Kernel project for a single-agent waste sorting advisor. The agent recommends the correct disposal method for an item based on the item material and the user's local recycling rules.

The project includes:

- Agent Kernel CLI entry point using the OpenAI Agents SDK.
- A lookup tool backed by structured disposal rules embedded in `tool.py`.
- Agent Kernel session memory for region-specific rules and remembered session regions.
- AWS Lambda deployment with DynamoDB-backed session persistence.

## Prerequisites

- Python 3.12.
- `uv` for dependency management.
- An OpenAI API key for local CLI use and AWS Lambda runtime.
- AWS CLI configured with credentials for the target AWS account.
- Terraform 1.9.5 or newer for deployment.
- Docker for building the Lambda container image used by Terraform.

## Project Layout

- `demo.py` registers the `waste_sorting_advisor` Agent Kernel agent.
- `lambda.py` registers the same agent for AWS Lambda via `agentkernel.aws.Lambda`.
- `agent.py` holds the shared OpenAI Agents SDK definition used by both entry points.
- `tool.py` contains Agent Kernel tools: `lookup_disposal_category`, `remember_region_rule`, and `get_region_memory`.
- `config.yaml` configures Agent Kernel local sessions and test mode.
- `deploy/` contains Terraform for AWS serverless deployment.

## Setup

```bash
chmod +x build.sh
./build.sh
```

For interactive Agent Kernel CLI usage, set an OpenAI API key:

```bash
export OPENAI_API_KEY="sk-..."
uv run python demo.py
```

Inside the CLI, the default agent is `waste_sorting_advisor`. You can also run:

```text
!list
!select waste_sorting_advisor
```

## AWS Lambda Deployment

`demo.py` is for local CLI usage. `lambda.py` is the AWS Lambda entry point and registers the same `waste_sorting_advisor` agent with `handler = Lambda.handler`.

The Terraform deployment uses Agent Kernel's AWS serverless module in synchronous REST mode and DynamoDB for session storage. Region-specific rules remembered by the agent are stored in Agent Kernel's non-volatile session cache, which becomes durable through DynamoDB in Lambda.

Build the Lambda image context:

```bash
chmod +x build_aws.sh
./build_aws.sh
```

Deploy with Terraform:

```bash
cd deploy
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars and set openai_api_key.
terraform init
terraform plan
terraform apply
```

Invoke the deployed agent:

```bash
AGENT_INVOKE_URL="$(terraform output -raw agent_invoke_url)"

curl -X POST "$AGENT_INVOKE_URL" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "I am in Colombo, LK. How should I dispose of a plastic grocery bag?",
    "session_id": "waste-demo-1",
    "agent": "waste_sorting_advisor"
  }'
```

Example API body:

```json
{
  "prompt": "I am in Colombo, LK. How should I dispose of a plastic grocery bag?",
  "session_id": "waste-demo-1",
  "agent": "waste_sorting_advisor"
}
```

Useful Terraform variables:

- `region`: AWS region, default `us-east-1`.
- `product_alias`: resource prefix, default `ak`.
- `env_alias`: environment alias, default `dev`.
- `module_name`: module namespace, default `waste-sorting`.
- `openai_api_key`: OpenAI API key loaded from `terraform.tfvars`.
- `dynamodb_session_table_name`: optional override for the DynamoDB session table name.

Terraform injects these Lambda environment variables for DynamoDB sessions:

```text
AK_SESSION__TYPE=dynamodb
AK_SESSION__DYNAMODB__TABLE_NAME=<session table>
AK_SESSION__CACHE__SIZE=256
```
