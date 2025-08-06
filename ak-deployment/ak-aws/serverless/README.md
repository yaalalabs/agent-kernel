# Terraform Module: ak-aws/serverless

A Terraform module for deploying serverless applications on AWS, combining Lambda functions with API Gateway to create RESTful APIs.

## Overview

This module simplifies the deployment of serverless applications by provisioning and configuring:

- AWS Lambda functions with customizable runtime, memory, and timeout settings
- API Gateway REST API with a structured endpoint path
- Integration between Lambda and API Gateway
- Support for multiple deployment methods (local zip, S3 zip, container image)
- Optional code signing for production environments

The module is designed for Agent Kernel deployments but can be used for any serverless application that follows the same pattern.

## Requirements

| Name | Version |
|------|---------|
| terraform | >= 1.9.5 |
| aws | 6.7.0 |

## Usage

```hcl
module "serverless_api" {
  source = "ak-aws/serverless"

  region              = "us-west-2"
  product_alias       = "myproduct"
  env_alias           = "dev"
  product_display_name = "My Product API"
  
  module_name         = "api"
  function_name       = "handler"
  function_description = "API Handler Function"
  handler_path        = "index.handler"
  module_type         = "nodejs"  # or "python"
  
  # For zip deployment
  package_type        = "LocalZip"  # or "S3Zip" or "Image"
  package_path        = "./dist/function.zip"
  
  # For container image deployment
  # package_type      = "Image"
  # image_uri         = "123456789012.dkr.ecr.us-west-2.amazonaws.com/my-function:latest"
  
  timeout             = 30
  memory_size         = 256
  
  environment_variables = {
    ENV = "development"
    LOG_LEVEL = "info"
  }
  
  api_version         = "v1"
  agent_endpoint      = "chat"
  
  tags = {
    Environment = "development"
    Project     = "MyProject"
  }
}
```

## Inputs

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|:--------:|
| region | AWS region for deployment | `string` | n/a | yes |
| product_alias | Short name for the product | `string` | n/a | yes |
| env_alias | Environment name (dev, staging, prod) | `string` | n/a | yes |
| product_display_name | Human-readable product name | `string` | "An Agent Kernel deployment" | no |
| module_type | Runtime type (python or nodejs) | `string` | "python" | no |
| module_name | Module name for resource naming | `string` | n/a | yes |
| is_production | Whether this is a production deployment | `bool` | false | no |
| package_path | Path to the Lambda deployment package | `string` | n/a | yes |
| event_source_mapping | Event source mapping configuration | `any` | [] | no |
| environment_variables | Environment variables for Lambda | `any` | {} | no |
| timeout | Lambda function timeout in seconds | `number` | 30 | no |
| memory_size | Lambda function memory size in MB | `number` | 128 | no |
| function_name | Lambda function name suffix | `string` | n/a | yes |
| function_description | Lambda function description | `string` | n/a | yes |
| handler_path | Path to the Lambda handler | `string` | n/a | yes |
| image_uri | Container image URI for Lambda | `string` | null | no |
| package_type | Deployment package type (LocalZip, S3Zip, Image) | `string` | "LocalZip" | no |
| layers | List of Lambda layer ARNs | `list(string)` | [] | no |
| api_version | API version for the endpoint path | `string` | "v1" | no |
| agent_endpoint | API endpoint name | `string` | "chat" | no |
| tags | Resource tags | `map(string)` | {} | no |

## Outputs

| Name | Description |
|------|-------------|
| lambda_function_arn | ARN of the Lambda function |
| lambda_function_name | Name of the Lambda function |
| lambda_function_invoke_arn | Invoke ARN of the Lambda function |
| agent_invoke_url | Full URL to invoke the API endpoint |

## Features

### Lambda Function Configuration

The module supports multiple deployment methods:
- **LocalZip**: Deploy from a local zip file
- **S3Zip**: Deploy from a zip file in S3 (with optional code signing)
- **Image**: Deploy from a container image

Runtime is automatically set based on `module_type`:
- `nodejs` → nodejs22.x
- `python` → python3.12

### API Gateway Configuration

Creates a REST API with the following path structure:
```
/api/{api_version}/{agent_endpoint}
```

For example, with default settings: `/api/v1/chat`

The API is deployed to a stage named "agents".

### Security Features

- Optional code signing for production deployments
- CloudWatch logs retention set to 90 days
- Support for KMS encryption (when keys are provided)

## Notes

- For production deployments, set `is_production = true` to enable code signing
- When using S3Zip deployment, the source code must be uploaded to the S3 bucket before applying this module
- The module creates all necessary IAM roles and permissions for Lambda execution