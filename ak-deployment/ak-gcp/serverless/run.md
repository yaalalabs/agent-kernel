# How to Run GCP Serverless Module

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
gcloud services enable cloudfunctions.googleapis.com
gcloud services enable cloudbuild.googleapis.com
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
cd ak-deployment/ak-gcp/serverless

terraform init
terraform validate
terraform fmt -check
```

---

## Deploy

```bash
cd ak-deployment/ak-gcp/serverless

terraform init

# Preview what will be created
terraform plan \
  -var="project_id=my-project-123" \
  -var="region=us-central1" \
  -var="product_alias=myapp" \
  -var="env_alias=dev" \
  -var="module_name=chatbot" \
  -var="function_name=my-agent" \
  -var="package_path=../../../examples/aws-serverless/openai/dist"

# Deploy
terraform apply \
  -var="project_id=my-project-123" \
  -var="region=us-central1" \
  -var="product_alias=myapp" \
  -var="env_alias=dev" \
  -var="module_name=chatbot" \
  -var="function_name=my-agent" \
  -var="package_path=../../../examples/aws-serverless/openai/dist"
```

Or use a tfvars file to avoid repeating vars:

```bash
# Create a tfvars file
cat > dev.tfvars <<EOF
project_id     = "my-project-123"
region         = "us-central1"
product_alias  = "myapp"
env_alias      = "dev"
module_name    = "chatbot"
function_name  = "my-agent"
package_path   = "../../../examples/aws-serverless/openai/dist"
environment_variables = {
  OPENAI_API_KEY = "sk-your-key-here"
}
EOF

# Then just
terraform plan -var-file="dev.tfvars"
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

# With both
terraform apply -var-file="dev.tfvars" \
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
# Get the deployed URL
terraform output agent_invoke_url

# Hit it
curl -X POST $(terraform output -raw agent_invoke_url) \
  -H "Content-Type: application/json" \
  -d '{"message": "hello"}'
```

---

## Check Logs

```bash
# Cloud Function logs
gcloud functions logs read myapp-dev-chatbot-function \
  --region=us-central1 --gen2 --limit=50

# API Gateway logs
gcloud logging read 'resource.type="apigateway.googleapis.com/Gateway"' \
  --limit=20
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
| function_url | Direct Cloud Function URL |
| function_name | Cloud Function name (for gcloud commands) |
| function_service_account | Service account email |
| gateway_url | API Gateway hostname |
| agent_invoke_url | Full URL to invoke: https://gateway-url/api/v1/chat |
