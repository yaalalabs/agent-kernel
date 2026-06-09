# Terraform Dependency Injection

This directory contains tools for injecting dependencies into AWS, Azure, and GCP example projects for local development and CI/CD.

## Files

### `backend.tf.<cloud>.template`
Per-cloud template files for the Terraform remote state backend, with placeholders that are replaced with project-specific values during injection:
- `backend.tf.aws.template` — S3 backend (with native state locking via `use_lockfile`)
- `backend.tf.azure.template` — Azure Storage (`azurerm`) backend
- `backend.tf.gcp.template` — Google Cloud Storage (`gcs`) backend

### `state-config.yaml`
Default state backend settings per cloud (bucket / account / project / region). Values here are used by both `setup_backend.sh` and `inject_dependencies.py`, and can be overridden via CLI flags.

### `setup_backend.sh`
**OPTIONAL** multi-cloud shell script that creates the required infrastructure for Terraform remote state:
- `aws` — S3 bucket for state storage (with versioning and encryption)
- `azure` — Resource group, storage account and blob container
- `gcp` — GCS bucket (with versioning)

This script is NOT automatically injected into projects. You can manually copy it if needed.

### `inject_dependencies.py`
Python script that performs three key tasks:

1. **Injects backend.tf files**: Generates `backend.tf` from the template with project-specific values and injects it into each project's deploy directory

2. **Modifies main.tf for local development**: Replaces Terraform registry module sources with local relative paths in example projects
   - Replaces `yaalalabs/ak-serverless/{aws,azurerm,google}` with the matching `ak-deployment/ak-{aws,azure,gcp}/serverless`
   - Replaces `yaalalabs/ak-containerized/{aws,azurerm,google}` with the matching `ak-deployment/ak-{aws,azure,gcp}/containerized`
   - Comments out `version` lines since they're not needed for local modules

3. **Modifies Terraform files for local development**: Replaces Terraform registry module sources with local relative paths in all `.tf` files under the deployment trees and example projects
  - Scans `ak-deployment/ak-aws`, `ak-deployment/ak-azure`, `ak-deployment/ak-gcp`, and `examples` recursively
  - Replaces `yaalalabs/ak-common/{aws,azurerm,google}//modules/*` with local relative paths
  - Handles nested module directories as well as top-level `state.tf` files
  - Comments out `version` lines for local module references

The script reads `.github/integration-test-config.yaml` to identify AWS, Azure, and GCP projects.

## Usage

### Inject Dependencies

Run the injection script from the workspace root:

```bash
python3 scripts/deploy/inject_dependencies.py
```

This will:
- Inject `backend.tf` into all AWS, Azure, and GCP example projects listed in the integration config
- Modify `main.tf` files to use local module sources
- Modify Terraform files under `ak-deployment` to use local common modules and nested module sources

### Revert to Registry Modules

To revert `main.tf` files back to using Terraform registry modules:

```bash
python3 scripts/deploy/inject_dependencies.py --revert
```

This will:
- Replace local module paths with registry sources
- Uncomment `version` lines
- Restore all modified Terraform files under the deployment trees to their original state

### Setting Up Backend Infrastructure (Optional)

If you want to use remote state, you need to create the backend storage first. The script takes a cloud (`aws`, `azure`, or `gcp`) and reads defaults from `state-config.yaml`, which can be overridden via flags:

```bash
# AWS S3 bucket
./scripts/deploy/setup_backend.sh aws --bucket my-tf-state --region ap-southeast-2

# Azure storage account + container
./scripts/deploy/setup_backend.sh azure --storage mystorageacct --container tfstate --resource-group my-rg

# GCP GCS bucket
./scripts/deploy/setup_backend.sh gcp --bucket my-tf-state --region us-east1
```

Or run with the defaults from `state-config.yaml`:

```bash
./scripts/deploy/setup_backend.sh gcp
```

Make sure you are authenticated with the relevant CLI (`aws`, `az`, or `gcloud`) and have `yq` installed. After running the setup script, the matching `backend.tf` injected by `inject_dependencies.py` will reference the same values.

## Notes

- **All modifications are for local development/CI/CD** - They allow testing with local module code instead of published registry versions
- `backend.tf` files are gitignored and only exist locally after injection
- Terraform files under `ak-deployment` are tracked in git but modified locally for development - use `--revert` to restore them before committing changes
- The template uses placeholder values that should be customized per environment
- Each project gets a unique state key based on its path
- Module sources use relative paths calculated from the file's location

## What Gets Modified

### backend.tf (injected)
```hcl
terraform {
  backend "s3" {
    bucket         = "agent-kernel-terraform-state-bucket"
    key            = "examples/aws-serverless/adk/terraform.tfstate"
    region         = "ap-southeast-2"
    dynamodb_table = "ak-terraform-state-lock"
    encrypt        = true
  }
}
```

### main.tf (modified)
**Before:**
```hcl
module "serverless_agents" {
  source = "yaalalabs/ak-serverless/aws"
  version = "0.2.11"
  ...
}
```

**After:**
```hcl
module "serverless_agents" {
  source = "../../../../ak-deployment/ak-aws/serverless"
  # version = "0.2.11"  # Commented for local development
  ...
}
```

## Customization

To customize the backend configuration, edit `backend.tf.template` and modify the `generate_backend_tf()` function in `inject_dependencies.py` to use your desired values for:
- S3 bucket name
- DynamoDB table name
- AWS region
- State key pattern
