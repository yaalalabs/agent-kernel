# How to Run GCP Common Modules

Common modules are building blocks. They don't run on their own - the serverless and containerized modules call them automatically.

But if you want to validate the code, here's how.

---

## Prerequisites (one-time setup)

```bash
# Install tools
brew install terraform
brew install google-cloud-sdk

# Login
gcloud auth login
gcloud auth application-default login

# Set project
gcloud config set project YOUR_PROJECT_ID

# Enable APIs
gcloud services enable compute.googleapis.com
gcloud services enable artifactregistry.googleapis.com
gcloud services enable redis.googleapis.com
gcloud services enable firestore.googleapis.com
gcloud services enable vpcaccess.googleapis.com
```

---

## Validate the Code

```bash
cd ak-deployment/ak-gcp/common

# Check syntax
terraform init
terraform validate
```

---

## Validate Individual Sub-Modules

```bash
# VPC
cd ak-deployment/ak-gcp/common/modules/vpc
terraform init
terraform validate

# Artifact Registry
cd ak-deployment/ak-gcp/common/modules/artifact-registry
terraform init
terraform validate

# GCS (Cloud Storage)
cd ak-deployment/ak-gcp/common/modules/gcs
terraform init
terraform validate

# Firestore
cd ak-deployment/ak-gcp/common/modules/firestore
terraform init
terraform validate

# Memorystore (Redis)
cd ak-deployment/ak-gcp/common/modules/memorystore
terraform init
terraform validate
```

---

## Format Check

```bash
# Check formatting for all files
cd ak-deployment/ak-gcp/common
terraform fmt -check -recursive

# Auto-fix formatting
terraform fmt -recursive
```

---

## What Each Sub-Module Creates

| Module | Resources Created |
|--------|-------------------|
| vpc | VPC, public subnet, private subnet, Cloud Router, Cloud NAT, firewall rule |
| artifact-registry | Artifact Registry repo, Docker image build + push |
| gcs | GCS bucket with versioning and optional KMS encryption |
| firestore | Firestore database, TTL field, composite index |
| memorystore | Memorystore Redis 7.0 instance with auth |

---

## Notes

- You don't need to run these directly
- The serverless module calls: vpc, artifact-registry, gcs, memorystore, firestore
- The containerized module calls: vpc, artifact-registry, memorystore, firestore
- They pull these modules from Terraform Registry: `yaalalabs/ak-common/google//modules/xxx`
