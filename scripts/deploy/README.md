# Terraform Dependency Injection

This directory contains tools for injecting dependencies into AWS example projects for local development and CI/CD.

## Files

### `backend.tf.template`
Template file for Terraform S3 backend configuration with DynamoDB state locking. This file contains placeholders that are replaced with project-specific values during injection.

### `setup_backend.sh`
**OPTIONAL** shell script that creates the required AWS infrastructure for Terraform remote state:
- S3 bucket for state storage (with versioning and encryption)
- DynamoDB table for state locking

This script is NOT automatically injected into projects. You can manually copy it if needed.

### `inject_dependencies.py`
Python script that performs three key tasks:

1. **Injects backend.tf files**: Generates `backend.tf` from the template with project-specific values and injects it into each project's deploy directory

2. **Modifies main.tf for local development**: Replaces Terraform registry module sources with local relative paths in example projects
   - Replaces `yaalalabs/ak-serverless/aws` with `../../../../ak-deployment/ak-aws/serverless`
   - Replaces `yaalalabs/ak-containerized/aws` with `../../../../ak-deployment/ak-aws/containerized`
   - Comments out `version` lines since they're not needed for local modules

3. **Modifies state.tf for local development**: Replaces Terraform registry common module sources with local relative paths in module directories
   - In `ak-deployment/ak-aws/serverless/state.tf` and `ak-deployment/ak-aws/containerized/state.tf`
   - Replaces `yaalalabs/ak-common/aws//modules/*` with `../common/modules/*`
   - Comments out `version` lines for local module references

The script reads `.github/integration-test-config.yaml` to identify AWS projects.

## Usage

### Inject Dependencies

Run the injection script from the workspace root:

```bash
python3 scripts/deploy/inject_dependencies.py
```

This will:
- Inject `backend.tf` into all AWS example projects
- Modify `main.tf` files to use local module sources
- Modify `state.tf` files in module directories to use local common modules

### Revert to Registry Modules

To revert `main.tf` files back to using Terraform registry modules:

```bash
python3 scripts/deploy/inject_dependencies.py --revert
```

This will:
- Replace local module paths with registry sources
- Uncomment `version` lines
- Restore all `main.tf` and `state.tf` files to their original state

### Setting Up Backend Infrastructure (Optional)

If you want to use remote state, you need to create the S3 bucket and DynamoDB table first. 

Copy the setup script to your project:

```bash
cp scripts/deploy/setup_backend.sh examples/aws-serverless/adk/deploy/
cd examples/aws-serverless/adk/deploy
./setup_backend.sh my-terraform-state terraform-lock ap-southeast-2
```

Or run with defaults:

```bash
./setup_backend.sh
# Uses: agent-kernel-terraform-state-bucket, ak-terraform-state-lock, ap-southeast-2
```

After running the setup script, update the `backend.tf` file with the same values.

## Notes

- **All modifications are for local development/CI/CD** - They allow testing with local module code instead of published registry versions
- `backend.tf` files are gitignored and only exist locally after injection
- `main.tf` and `state.tf` files are tracked in git but modified locally for development - use `--revert` to restore them before committing changes
- `main.tf` files are tracked in git but can be easily reverted using `--revert` flag
- The template uses placeholder values that should be customized per environment
- Each project gets a unique state key based on its path
- Module sources use relative paths calculated from the example's deploy directory

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
