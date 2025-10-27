# Lambda Package Module

A Terraform module for managing AWS Lambda function and layer deployment packages in S3 with versioning, checksums, and organized storage structure.

## 📋 Overview

This module streamlines Lambda package management in S3:

- 📦 **Package Upload**: Automated ZIP package upload to S3
- 📁 **Organized Structure**: Consistent S3 key patterns for easy navigation
- 🔄 **Version Control**: File checksum-based versioning for change detection
- 🏷️ **Type Support**: Handles both function packages and layer packages
- 🔍 **Smart Detection**: References existing packages when local file unavailable
- 🎯 **Lambda Ready**: Outputs optimized for Lambda resource configuration

Perfect for CI/CD pipelines, multi-environment deployments, and automated Lambda package management.

## 📋 Requirements

| Name | Version |
|------|---------|
| Terraform | >= 1.9.5 |
| AWS Provider | >= 6.11.0 |

## 🚀 Usage

### Basic Lambda Function Package

```hcl
# Create S3 bucket for packages
module "lambda_storage" {
  source = "yaalalabs/ak-common/aws//modules/s3"

  region               = "us-west-2"
  product_alias        = "myapp"
  env_alias            = "prod"
  product_display_name = "Lambda Packages"
  is_production        = true
}

# Upload Lambda function package
module "api_package" {
  source = "yaalalabs/ak-common/aws//modules/lambda-package"

  region           = "us-west-2"
  product_alias    = "myapp"
  env_alias        = "prod"
  module_name      = "api"
  package_dir_path = "${path.module}/dist/api-function.zip"
  s3_bucket        = module.lambda_storage.source_storage_s3_bucket
  is_layer         = false
}

# Create Lambda function using the package
resource "aws_lambda_function" "api" {
  function_name = "myapp-prod-api"
  s3_bucket     = module.api_package.s3_bucket
  s3_key        = module.api_package.s3_key
  handler       = "index.handler"
  runtime       = "nodejs18.x"
  role          = aws_iam_role.lambda_role.arn
}
```

### Lambda Layer Package

```hcl
# Upload Lambda layer package
module "shared_layer" {
  source = "yaalalabs/ak-common/aws//modules/lambda-package"

  region           = "us-west-2"
  product_alias    = "myapp"
  env_alias        = "prod"
  module_name      = "shared-libs"
  package_dir_path = "${path.module}/dist/layer.zip"
  s3_bucket        = module.lambda_storage.source_storage_s3_bucket
  is_layer         = true  # Marks as layer package
}

# Create Lambda layer
resource "aws_lambda_layer_version" "shared" {
  layer_name          = "myapp-shared-libs"
  s3_bucket           = module.shared_layer.s3_bucket
  s3_key              = module.shared_layer.s3_key
  compatible_runtimes = ["python3.11", "python3.12"]
}
```

### Multi-Environment Deployment

```hcl
# Development environment
module "dev_package" {
  source = "yaalalabs/ak-common/aws//modules/lambda-package"

  region           = "us-west-2"
  product_alias    = "myapp"
  env_alias        = "dev"
  module_name      = "worker"
  package_dir_path = "${path.module}/dist/worker-dev.zip"
  s3_bucket        = module.dev_storage.source_storage_s3_bucket
}

# Production environment
module "prod_package" {
  source = "yaalalabs/ak-common/aws//modules/lambda-package"

  region              = "us-west-2"
  product_alias       = "myapp"
  env_alias           = "prod"
  module_name         = "worker"
  package_dir_path    = "${path.module}/dist/worker-prod.zip"
  s3_bucket           = module.prod_storage.source_storage_s3_bucket
  is_production       = true
  product_display_name = "My Application"
}
```

### CI/CD Pipeline Integration

```hcl
# Package built by CI/CD pipeline
module "ci_package" {
  source = "yaalalabs/ak-common/aws//modules/lambda-package"

  region           = "us-west-2"
  product_alias    = "myapp"
  env_alias        = var.environment
  module_name      = "api"
  package_dir_path = "${path.module}/artifacts/api-${var.build_version}.zip"
  s3_bucket        = var.lambda_bucket
  
  # Use build metadata
  is_production       = var.environment == "prod"
  product_display_name = "API Service v${var.build_version}"
}
```


## 📥 Inputs

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|:--------:|
| `region` | AWS region for deployment | `string` | `"ap-southeast-2"` | no |
| `product_alias` | Short identifier for the product (e.g., "myapp") | `string` | n/a | yes |
| `env_alias` | Environment identifier (e.g., "dev", "staging", "prod") | `string` | n/a | yes |
| `product_display_name` | Human-readable product name for tagging | `string` | `null` | no |
| `is_production` | Production flag for additional safeguards | `bool` | `false` | no |
| `module_name` | Module/service name for resource identification | `string` | n/a | yes |
| `package_dir_path` | Path to Lambda function or layer ZIP package | `string` | n/a | yes |
| `is_layer` | Whether package is a Lambda layer (true) or function (false) | `bool` | `false` | no |
| `s3_bucket` | S3 bucket name for package storage | `string` | n/a | yes |

## 📤 Outputs

| Name | Description | Example |
|------|-------------|---------|
| `s3_bucket` | S3 bucket name containing the package | `myapp-prod-sources-123456789012` |
| `s3_key` | S3 object key for the package | `myapp/us-west-2/prod/api/function/api-function.zip` |
| `s3_object_version` | Version ID of the S3 object | `abc123def456` |
| `package_etag` | ETag/checksum of the package | `"d41d8cd98f00b204e9800998ecf8427e"` |
| `package_size` | Size of the package in bytes | `1048576` |

## ✨ Features

### 📁 Organized S3 Structure

The module creates a hierarchical S3 key structure:

```
{product_alias}/{region}/{env_alias}/{module_name}/{package_type}/{filename}
                                                     └── "function" or "layer"
```

**Example**:
```
myapp/us-west-2/prod/api/function/api-handler.zip
myapp/us-west-2/prod/shared/layer/dependencies.zip
myapp/us-west-2/dev/worker/function/worker.zip
```

### 🔄 Version Management

- **Checksum Tracking**: Uses file MD5 hash (etag) to detect changes
- **Automatic Updates**: Uploads new version when local file changes
- **Reference Mode**: If local file doesn't exist, references existing S3 object
- **Terraform State**: Tracks package versions in state file

### 📦 Package Type Support

**Function Packages** (`is_layer = false`):
- Contains Lambda function code and dependencies
- Stored in `/function/` subdirectory
- Used with `aws_lambda_function` resource

**Layer Packages** (`is_layer = true`):
- Contains shared libraries and dependencies
- Stored in `/layer/` subdirectory
- Used with `aws_lambda_layer_version` resource

## 🎯 Best Practices

### 1. Separate Buckets by Environment

```hcl
# Development bucket
module "dev_storage" {
  source = "yaalalabs/ak-common/aws//modules/s3"
  
  product_alias = "myapp"
  env_alias     = "dev"
  # ... other config
}

# Production bucket (with versioning)
module "prod_storage" {
  source = "yaalalabs/ak-common/aws//modules/s3"
  
  product_alias = "myapp"
  env_alias     = "prod"
  is_production = true  # Enables versioning
  # ... other config
}
```

### 2. Build Packages Before Terraform

Ensure ZIP packages are built before running Terraform:

```bash
# Build script
#!/bin/bash
set -e

# Build function package
cd src/api
zip -r ../../dist/api-function.zip .

# Build layer package
cd ../layers
pip install -r requirements.txt -t python/
zip -r ../../dist/layer.zip python/

# Run Terraform
cd ../..
terraform apply
```

### 3. Use Descriptive Module Names

```hcl
# Good: Descriptive names
module_name = "user-api"
module_name = "auth-service"
module_name = "shared-utilities-layer"

# Avoid: Generic names
module_name = "function1"
module_name = "lambda"
```

### 4. Version in Filenames for Releases

```hcl
# Include version in package filename
module "api_package" {
  package_dir_path = "${path.module}/dist/api-v${var.version}.zip"
  # ...
}
```

## 📦 Package Creation Examples

### Python Function Package

```bash
# Directory structure
src/
├── requirements.txt
└── lambda_function.py

# Create package
pip install -r requirements.txt -t package/
cp lambda_function.py package/
cd package && zip -r ../function.zip . && cd ..
```

### Node.js Function Package

```bash
# Directory structure
src/
├── package.json
└── index.js

# Create package
npm install
zip -r function.zip node_modules/ index.js package.json
```

### Lambda Layer Package

```bash
# Python layer structure
layer/
└── python/
    └── lib/
        └── (packages)

# Create layer
mkdir -p layer/python
pip install -r requirements.txt -t layer/python/
cd layer && zip -r ../layer.zip . && cd ..
```

## 🔗 Complete Example

### Full Deployment Pipeline

```hcl
# 1. Create S3 bucket
module "storage" {
  source = "yaalalabs/ak-common/aws//modules/s3"

  region               = "us-west-2"
  product_alias        = "myapp"
  env_alias            = "prod"
  product_display_name = "My Application"
  is_production        = true
}

# 2. Upload shared layer
module "layer_package" {
  source = "yaalalabs/ak-common/aws//modules/lambda-package"

  region           = "us-west-2"
  product_alias    = "myapp"
  env_alias        = "prod"
  module_name      = "dependencies"
  package_dir_path = "${path.module}/dist/layer.zip"
  s3_bucket        = module.storage.source_storage_s3_bucket
  is_layer         = true
}

# 3. Create Lambda layer
resource "aws_lambda_layer_version" "dependencies" {
  layer_name          = "myapp-dependencies"
  s3_bucket           = module.layer_package.s3_bucket
  s3_key              = module.layer_package.s3_key
  compatible_runtimes = ["python3.11"]
}

# 4. Upload function package
module "function_package" {
  source = "yaalalabs/ak-common/aws//modules/lambda-package"

  region           = "us-west-2"
  product_alias    = "myapp"
  env_alias        = "prod"
  module_name      = "api"
  package_dir_path = "${path.module}/dist/function.zip"
  s3_bucket        = module.storage.source_storage_s3_bucket
  is_layer         = false
}

# 5. Create Lambda function
resource "aws_lambda_function" "api" {
  function_name = "myapp-prod-api"
  s3_bucket     = module.function_package.s3_bucket
  s3_key        = module.function_package.s3_key
  handler       = "lambda_function.handler"
  runtime       = "python3.11"
  role          = aws_iam_role.lambda_role.arn
  
  layers = [aws_lambda_layer_version.dependencies.arn]
  
  environment {
    variables = {
      ENVIRONMENT = "production"
    }
  }
}
```

## 🔍 Troubleshooting

### Package File Not Found

**Issue**: Terraform cannot find the package file
```
Error: no such file or directory
```

**Solution**: 
1. Build the package before running Terraform
2. Verify `package_dir_path` is correct:
   ```bash
   ls -lh dist/function.zip
   ```

### Package Too Large

**Issue**: Lambda deployment fails due to package size
```
Error: Package size exceeded
```

**Limits**:
- Direct upload: 50 MB (zipped)
- S3 upload: 250 MB (unzipped)

**Solutions**:
1. **Use Layers**: Extract dependencies to a layer
2. **Optimize**: Remove unnecessary files
3. **Use `.zipignore`**: Exclude test files, docs
4. **Container Images**: For packages > 250 MB, use ECR module

### Package Not Updating

**Issue**: Lambda still using old code after Terraform apply

**Solution**: Verify package changed:
```bash
# Check file changed
md5sum dist/function.zip

# Force Terraform to detect change
terraform taint module.function_package.aws_s3_object.package
terraform apply
```

### S3 Bucket Access Denied

**Issue**: Cannot upload package to S3
```
Error: Access Denied
```

**Solution**: Ensure IAM permissions include:
```json
{
  "Effect": "Allow",
  "Action": [
    "s3:PutObject",
    "s3:PutObjectAcl",
    "s3:GetObject"
  ],
  "Resource": "arn:aws:s3:::bucket-name/*"
}
```

## 💡 Advanced Patterns

### Blue-Green Deployments

```hcl
# Upload new version
module "api_package_v2" {
  source = "yaalalabs/ak-common/aws//modules/lambda-package"

  module_name      = "api-v2"
  package_dir_path = "${path.module}/dist/api-v2.zip"
  # ... other config
}

# Create alias for versioning
resource "aws_lambda_alias" "api_live" {
  name             = "live"
  function_name    = aws_lambda_function.api.arn
  function_version = aws_lambda_function.api.version
}
```

### Automated Versioning

```hcl
locals {
  git_commit = trimspace(file("${path.module}/.git/refs/heads/main"))
  version    = substr(local.git_commit, 0, 7)
}

module "versioned_package" {
  source = "yaalalabs/ak-common/aws//modules/lambda-package"

  package_dir_path    = "${path.module}/dist/function-${local.version}.zip"
  product_display_name = "API v${local.version}"
  # ... other config
}
```

## 📚 Additional Resources

- [AWS Lambda Deployment Packages](https://docs.aws.amazon.com/lambda/latest/dg/gettingstarted-package.html)
- [Lambda Layers](https://docs.aws.amazon.com/lambda/latest/dg/configuration-layers.html)
- [Lambda Package Size Limits](https://docs.aws.amazon.com/lambda/latest/dg/gettingstarted-limits.html)

## 🔗 Related Modules

- [S3 Module](../s3/) - For creating Lambda package storage buckets
- [ECR Module](../ecr/) - For container-based Lambda deployments (>250 MB)

---

**Note**: This module uploads packages but does not create them. Ensure your ZIP packages are built before running Terraform. The S3 bucket must exist before using this module.