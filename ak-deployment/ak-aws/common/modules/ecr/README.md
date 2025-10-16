# ECR Module

A Terraform module for building Docker container images and storing them in Amazon Elastic Container Registry (ECR) for AWS Lambda functions and ECS deployments.

## 📋 Overview

This module automates the complete Docker image lifecycle for serverless and containerized applications:

- 🏗️ Creates and manages Amazon ECR repositories with standardized naming
- 🐳 Builds Docker images from source code with automatic platform targeting
- 🔄 Implements lifecycle policies for automatic image retention management
- 📦 Provides ready-to-use image URIs for Lambda and ECS deployments
- 🔍 Tracks source code changes to trigger automatic rebuilds

Perfect for serverless applications, microservices, and containerized workloads requiring automated image management.

## 📋 Requirements

| Name | Version |
|------|---------|
| Terraform | >= 1.9.5 |
| AWS Provider | >= 6.11.0 |
| Docker | Latest |

## 🚀 Usage

### Basic Example

```hcl
module "api_container" {
  source = "app.terraform.io/yaalalabs/ak-aws-common/aws//modules/ecr"

  region        = "us-west-2"
  product_alias = "myapp"
  env_alias     = "prod"
  module_name   = "api"
  source_path   = "${path.module}/src/api"
}

# Use the image URI in Lambda function
resource "aws_lambda_function" "api" {
  function_name = "myapp-prod-api"
  package_type  = "Image"
  image_uri     = module.api_container.docker_image_uri
  role          = aws_iam_role.lambda_role.arn
}
```

### Multi-Environment Setup

```hcl
# Development environment
module "dev_container" {
  source = "app.terraform.io/yaalalabs/ak-aws-common/aws//modules/ecr"

  region              = "us-west-2"
  product_alias       = "myapp"
  env_alias           = "dev"
  module_name         = "worker"
  source_path         = "${path.module}/src/worker"
  is_production       = false
}

# Production environment
module "prod_container" {
  source = "app.terraform.io/yaalalabs/ak-aws-common/aws//modules/ecr"

  region              = "us-west-2"
  product_alias       = "myapp"
  env_alias           = "prod"
  module_name         = "worker"
  source_path         = "${path.module}/src/worker"
  is_production       = true
  product_display_name = "My Application"
}
```


## 📥 Inputs

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|:--------:|
| `region` | AWS region for ECR repository deployment | `string` | `"ap-southeast-2"` | no |
| `product_alias` | Short identifier for the product (e.g., "myapp") | `string` | n/a | yes |
| `env_alias` | Environment identifier (e.g., "dev", "staging", "prod") | `string` | n/a | yes |
| `product_display_name` | Human-readable product name for tagging | `string` | `null` | no |
| `is_production` | Production flag for additional safeguards | `bool` | `false` | no |
| `module_name` | Module/service name for resource identification | `string` | n/a | yes |
| `source_path` | Path to directory containing Dockerfile and source code | `string` | n/a | yes |

## 📤 Outputs

| Name | Description | Example |
|------|-------------|---------|
| `docker_image_uri` | Complete ECR image URI for Lambda/ECS deployment | `123456789012.dkr.ecr.us-west-2.amazonaws.com/myapp-prod-api:latest` |
| `repository_url` | ECR repository URL | `123456789012.dkr.ecr.us-west-2.amazonaws.com/myapp-prod-api` |
| `repository_arn` | ARN of the ECR repository | `arn:aws:ecr:us-west-2:123456789012:repository/myapp-prod-api` |

## ✨ Features

### 🏗️ Automated Docker Build

- **Multi-platform Support**: Builds for `linux/amd64` platform (AWS Lambda compatible)
- **Change Detection**: Monitors source files and triggers rebuilds automatically
- **Build Optimization**: Leverages Docker layer caching for faster builds
- **Automatic Authentication**: Handles ECR authentication seamlessly

### 📦 Repository Management

- **Naming Convention**: Creates repositories with pattern `{product_alias}-{env_alias}-{module_name}`
- **Lifecycle Policies**: Automatically retains only the 30 most recent images
- **Image Scanning**: Optional vulnerability scanning on push
- **Immutable Tags**: Configurable tag immutability for production environments

### 🔒 Security

- **Private Repositories**: All repositories are private by default
- **IAM Integration**: Works with AWS IAM for access control
- **Encryption at Rest**: Images encrypted in ECR storage
- **Vulnerability Scanning**: Optional image scanning for security issues

## 📁 Source Directory Structure

Your source directory should contain a `Dockerfile` and application code:

```
src/
├── Dockerfile          # Required: Docker build instructions
├── requirements.txt    # Python dependencies (if applicable)
├── package.json        # Node.js dependencies (if applicable)
└── app/               # Application code
    ├── main.py
    └── utils.py
```

### Example Dockerfile for Python Lambda

```dockerfile
FROM public.ecr.aws/lambda/python:3.11

# Copy requirements and install dependencies
COPY requirements.txt ${LAMBDA_TASK_ROOT}
RUN pip install -r requirements.txt

# Copy application code
COPY app/ ${LAMBDA_TASK_ROOT}/app/

# Set the CMD to your handler
CMD ["app.main.handler"]
```

## 🎯 Best Practices

1. **Use Multi-Stage Builds**: Reduce image size by using multi-stage Dockerfiles
2. **Pin Base Images**: Specify exact base image versions for reproducibility
3. **Minimize Layers**: Combine RUN commands to reduce image layers
4. **Security Scanning**: Enable image scanning for production environments
5. **Tag Strategy**: Use semantic versioning or commit SHAs for production tags

## 🔍 Troubleshooting

### Build Fails with "No such file or directory"

**Issue**: Dockerfile not found in source_path
```
Error: Failed to build Docker image
```

**Solution**: Ensure your source_path contains a valid Dockerfile:
```bash
ls -la path/to/source/code/Dockerfile
```

### Authentication Errors

**Issue**: Docker cannot authenticate with ECR
```
Error: no basic auth credentials
```

**Solution**: Ensure AWS credentials are configured and have ECR permissions:
```bash
aws ecr get-login-password --region us-west-2 | docker login --username AWS --password-stdin <account>.dkr.ecr.us-west-2.amazonaws.com
```

### Image Too Large

**Issue**: Lambda deployment fails due to image size
```
Error: Unzipped size must be smaller than 10GB
```

**Solution**: Optimize your Docker image:
- Use slim base images (e.g., `python:3.11-slim`)
- Remove unnecessary files and dependencies
- Use `.dockerignore` to exclude files from the build context
- Implement multi-stage builds

## 📚 Additional Resources

- [AWS ECR Documentation](https://docs.aws.amazon.com/ecr/)
- [AWS Lambda Container Images](https://docs.aws.amazon.com/lambda/latest/dg/images-create.html)
- [Docker Best Practices](https://docs.docker.com/develop/dev-best-practices/)

## 🔗 Related Modules

- [Lambda Package Module](../lambda-package/) - For ZIP-based Lambda deployments
- [VPC Module](../vpc/) - For Lambda networking configuration

---

**Note**: This module requires Docker to be installed and running on the machine where Terraform is executed.