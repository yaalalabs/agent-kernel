---
name: ak-cloud-deploy
description: >
  Deploy an Agent Kernel project to AWS or Azure cloud. This skill guides you through
  choosing a cloud provider and deployment mode, generating Terraform configuration,
  setting up prerequisites, and deploying your agent. Supports AWS Lambda, AWS ECS/Fargate,
  Azure Functions, and Azure Container Apps.
license: Apache-2.0
metadata:
  author: yaalalabs
  category: user
---

# Deploy to Cloud

Use this skill to deploy your Agent Kernel project to AWS or Azure.

## Instructions for the Agent

When the user wants to deploy their agent to the cloud, follow this workflow:

### Step 1: Identify the Project

Check for an existing Agent Kernel project:
- `pyproject.toml` with `agentkernel` dependency
- An agent definition file
- A `config.yaml`

If not found, suggest using the `ak-init` skill first.

### Step 2: Ask Deployment Questions

1. **Cloud provider**: AWS or Azure?

2. **Deployment mode**:
   - **Serverless** (recommended for getting started — auto-scaling, pay-per-use)
     - AWS: Lambda + API Gateway
     - Azure: Functions (Flex Consumption) + API Management
   - **Containerized** (recommended for production — predictable performance, longer timeouts)
     - AWS: ECS Fargate + ALB + API Gateway
     - Azure: Container Apps + API Management

3. **Session persistence**: Do you need session persistence? (recommended for production)
   - AWS Serverless → DynamoDB (recommended) or Redis
   - AWS Containerized → Redis (recommended) or DynamoDB
   - Azure Serverless → Cosmos DB (recommended) or Redis
   - Azure Containerized → Redis (recommended) or Cosmos DB

4. **Custom domain**: Do you have a custom domain name? (optional)

5. **Environment**: What environment name? (e.g., `dev`, `staging`, `prod`)

### Step 3: Generate Deployment Files

#### AWS Serverless (Lambda)

**1. Update the main agent file to use Lambda handler:**

Rename/create as `lambda.py`:

```python
from agentkernel.aws import Lambda
from agentkernel.openai import OpenAIModule  # or other framework
from agents import Agent

# ... agent definitions ...

OpenAIModule([...])

handler = Lambda.handler
```

**2. Update pyproject.toml:**

```toml
dependencies = [
    "agentkernel[openai,redis]>=0.2.13",    # or dynamodb via aws extra
]
```

**3. Update config.yaml:**

```yaml
session:
  type: redis     # or dynamodb
  redis:
    prefix: "ak:<project>:"
    url: "${REDIS_URL}"    # will be set by Terraform
```

Or for DynamoDB:
```yaml
session:
  type: dynamodb
  dynamodb:
    table_name: "${DYNAMODB_TABLE}"
    region: "${AWS_REGION}"
```

**4. Create deploy/ directory with Terraform files:**

`deploy/main.tf`:
```hcl
module "serverless_agents" {
  source  = "yaalalabs/ak-serverless/aws"
  version = "0.2.13"

  product_alias        = var.product_alias
  env_alias            = var.env_alias
  function_description = "<description>"
  function_name        = "<function-name>"
  handler_path         = "lambda.handler"
  module_name          = var.module_name
  package_path         = "../dist"
  package_type         = "Image"
  memory_size          = 256
  create_redis_cluster = true         # set false if using existing Redis
  product_display_name = "<display-name>"
  region               = var.region

  environment_variables = {
    "OPENAI_API_KEY" = var.openai_api_key
    # Add other env vars as needed
  }
}
```

`deploy/variables.tf`:
```hcl
variable "region" {
  type = string
}

variable "product_alias" {
  type = string
}

variable "env_alias" {
  type = string
}

variable "module_name" {
  type = string
}

variable "openai_api_key" {
  type      = string
  sensitive = true
}
```

`deploy/outputs.tf`:
```hcl
output "agent_invoke_url" {
  description = "The URL to invoke the agent"
  value       = module.serverless_agents.agent_invoke_url
}
```

`deploy/terraform.tfvars`:
```hcl
region        = "<aws-region>"          # e.g., us-east-1
product_alias = "<product-name>"
env_alias     = "<environment>"         # dev, staging, prod
module_name   = "<module-name>"
```

`deploy/backend.tf`:
```hcl
terraform {
  backend "s3" {
    bucket         = "<your-terraform-state-bucket>"
    key            = "<project>/terraform.tfstate"
    region         = "<aws-region>"
    dynamodb_table = "<your-terraform-lock-table>"
    encrypt        = true
  }
}
```

`deploy/Dockerfile`:
```dockerfile
FROM public.ecr.aws/lambda/python:3.12
COPY data/ /var/task/
CMD ["lambda.handler"]
```

`deploy/deploy.sh`:
```bash
#!/bin/bash
set -e

# Create deployment package
pushd ../
rm -rf dist
mkdir -p dist/data
uv export --no-hashes > requirements.txt
uv pip install -r requirements.txt --target=dist/data
cp -r lambda.py config.yaml dist/data
# Copy any additional files (tool.py, etc.)
popd
cp Dockerfile ../dist/

# Deploy
terraform init
terraform apply
```

---

#### AWS Containerized (ECS Fargate)

**1. Use API mode in your agent file (`app.py`):**

```python
from agentkernel.api import RESTAPI
from agentkernel.openai import OpenAIModule
from agents import Agent

# ... agent definitions ...
OpenAIModule([...])

if __name__ == "__main__":
    RESTAPI.run()
```

**2. Create deploy/main.tf:**

```hcl
module "containerized_agents" {
  source  = "yaalalabs/ak-containerized/aws"
  version = "0.2.13"

  product_alias        = var.product_alias
  env_alias            = var.env_alias
  product_display_name = "<display-name>"
  region               = var.region
  create_redis_cluster = true
  container_port       = 8000

  environment_variables = {
    "OPENAI_API_KEY" = var.openai_api_key
  }
}
```

**3. Create deploy/Dockerfile:**

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["python", "app.py"]
```

---

#### Azure Serverless (Functions)

**1. Update agent file to use Azure handler:**

```python
from agentkernel.azure import AzureFunction
from agentkernel.openai import OpenAIModule
from agents import Agent

# ... agent definitions ...
OpenAIModule([...])

handler = AzureFunction.handler
```

**2. Create deploy/main.tf:**

```hcl
module "serverless_agents" {
  source  = "yaalalabs/ak-serverless/azurerm"
  version = "0.2.13"

  product_alias        = var.product_alias
  env_alias            = var.env_alias
  product_display_name = "<display-name>"
  region               = var.region
  create_redis          = true

  environment_variables = {
    "OPENAI_API_KEY" = var.openai_api_key
  }
}
```

---

#### Azure Containerized (Container Apps)

**1. Use API mode (same as AWS containerized)**

**2. Create deploy/main.tf:**

```hcl
module "containerized_agents" {
  source  = "yaalalabs/ak-containerized/azurerm"
  version = "0.2.13"

  product_alias        = var.product_alias
  env_alias            = var.env_alias
  product_display_name = "<display-name>"
  region               = var.region
  create_redis          = true
  container_port       = 8000

  environment_variables = {
    "OPENAI_API_KEY" = var.openai_api_key
  }
}
```

---

### Step 4: Prerequisites Checklist

Tell the user what they need before deploying:

**AWS:**
- [ ] AWS CLI installed and configured (`aws configure`)
- [ ] Terraform >= 1.9.5 installed
- [ ] S3 bucket for Terraform state (or remove backend.tf for local state)
- [ ] DynamoDB table for state locking (optional)
- [ ] API key for the LLM provider set as environment variable

**Azure:**
- [ ] Azure CLI installed and logged in (`az login`)
- [ ] Terraform >= 1.9.5 installed
- [ ] Azure Storage Account for Terraform state (or local state)
- [ ] API key for the LLM provider

### Step 5: Deploy

```bash
cd deploy
chmod +x deploy.sh
./deploy.sh
```

Or manually:
```bash
cd deploy
terraform init
terraform plan        # Review changes
terraform apply       # Deploy
```

After deployment, Terraform outputs the invoke URL. Test it:

```bash
curl -X POST <invoke-url>/run \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Hello!", "session_id": "test-1", "agent": "triage"}'
```

### Step 6: Teardown

To destroy the infrastructure:
```bash
cd deploy
terraform destroy
```
