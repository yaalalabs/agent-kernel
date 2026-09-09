# How to Run GCP Containerized Module

---

## Prerequisites (one-time setup)

```bash
# Install tools
brew install terraform
brew install google-cloud-sdk
brew install docker

# Login
gcloud auth login
gcloud auth application-default login

# Set project
gcloud config set project YOUR_PROJECT_ID

# Enable APIs
gcloud services enable compute.googleapis.com
gcloud services enable run.googleapis.com
gcloud services enable artifactregistry.googleapis.com
gcloud services enable apigateway.googleapis.com
gcloud services enable servicecontrol.googleapis.com
gcloud services enable servicemanagement.googleapis.com
gcloud services enable vpcaccess.googleapis.com
gcloud services enable redis.googleapis.com
gcloud services enable firestore.googleapis.com

# Make sure Docker is running
docker info
```

---

## Validate

```bash
cd ak-deployment/ak-gcp/containerized

terraform init
terraform validate
terraform fmt -check
```

---

## Deploy

```bash
cd ak-deployment/ak-gcp/containerized

terraform init

# Create a tfvars file
cat > dev.tfvars <<EOF
project_id     = "my-project-123"
region         = "us-central1"
product_alias  = "myapp"
env_alias      = "dev"
module_name    = "api"
package_path   = "../../../examples/aws-containerized/crewai/dist"
environment_variables = {
  OPENAI_API_KEY = "sk-your-key-here"
}
EOF

# Preview
terraform plan -var-file="dev.tfvars"

# Deploy
terraform apply -var-file="dev.tfvars"
```

---

## Deploy with Optional Features

```bash
# With Redis
terraform apply -var-file="dev.tfvars" \
  -var="create_redis_cluster=true"

# With Firestore
terraform apply -var-file="dev.tfvars" \
  -var="create_firestore_database=true"

# With MCP server endpoint
terraform apply -var-file="dev.tfvars" \
  -var="enable_mcp_server=true"

# With more resources (production)
terraform apply -var-file="dev.tfvars" \
  -var='cpu=2' \
  -var='memory=2Gi' \
  -var="min_instance_count=2" \
  -var="max_instance_count=50" \
  -var="create_redis_cluster=true" \
  -var="create_firestore_database=true"

# With existing VPC (skip VPC creation)
terraform apply -var-file="dev.tfvars" \
  -var="network_id=projects/my-project-123/global/networks/my-vpc" \
  -var="private_subnet_id=projects/my-project-123/regions/us-central1/subnetworks/my-subnet"
```

---

## Test

```bash
# Health check (direct Cloud Run URL)
curl $(terraform output -raw service_url)/health

# Agent endpoint (via API Gateway)
curl -X POST $(terraform output -raw agent_invoke_url) \
  -H "Content-Type: application/json" \
  -d '{"message": "hello"}'
```

---

## Check Logs

```bash
# Cloud Run logs
gcloud run services logs read myapp-dev-api-service \
  --region=us-central1 --limit=50

# Service details
gcloud run services describe myapp-dev-api-service \
  --region=us-central1

# VPC connector status
gcloud compute networks vpc-access connectors describe myapp-dev-run-conn \
  --region=us-central1

# List pushed Docker images
gcloud artifacts docker images list \
  us-central1-docker.pkg.dev/my-project-123/myapp-dev-api
```

---

## Redeploy After Code Changes

```bash
# Terraform detects file changes via dir_sha hash automatically
terraform apply -var-file="dev.tfvars"
```

---

## Destroy

```bash
terraform destroy -var-file="dev.tfvars"
```

---

## All Outputs

| Output | What it is |
|--------|------------|
| service_url | Direct Cloud Run URL (https://xxx-uc.a.run.app) |
| service_name | Cloud Run service name (for gcloud commands) |
| service_account_email | Service account email |
| gateway_url | API Gateway hostname |
| agent_invoke_url | Full URL to invoke: https://gateway-url/api/v1/chat |

---

## Troubleshooting

```bash
# Permission denied?
gcloud auth application-default login

# Docker not running?
docker info    # if this fails, start Docker Desktop

# VPC connector CIDR conflict?
# Change public_subnet_cidr or private_subnet_cidr in your tfvars

# Container not starting?
gcloud run services logs read myapp-dev-api-service --region=us-central1 --limit=20
# Check: does your container listen on port 8000? Does /health return 200?
```
