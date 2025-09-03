# Terraform Module: ECR

A Terraform module for building Docker images for AWS Lambda functions / ECS and storing them in Amazon ECR.

## Overview

This module simplifies the process of building Docker images for Lambda functions by:

- Creating an Amazon ECR repository to store Docker images
- Building Docker images from source code
- Setting up ECR repository lifecycle policies to manage image retention
- Providing the image URI for use in Lambda function deployments

The module is designed for Agent Kernel deployments but can be used for any Lambda function that requires containerization.

## Requirements

| Name | Version |
|------|---------|
| terraform | >= 1.9.5 |
| aws | 6.7.0 |

## Usage

```hcl
module "docker_image" {
  source  = "app.terraform.io/yaalalabs/ak-ecr/aws"
  version = "0.0.1"

  region        = "us-west-2"
  product_alias = "myproduct"
  env_alias     = "dev"
  module_name   = "api"
  source_path   = "path/to/source/code"
}
```

## Inputs

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|:--------:|
| region | AWS region for deployment | `string` | "ap-southeast-2" | no |
| product_alias | Short name for the product | `string` | n/a | yes |
| env_alias | Environment name (dev, staging, prod) | `string` | n/a | yes |
| product_display_name | Human-readable product name | `string` | null | no |
| is_production | Whether this is a production deployment | `bool` | false | no |
| module_name | Module name for resource naming | `string` | n/a | yes |
| source_path | Path to the source code for Docker image | `string` | n/a | yes |

## Outputs

| Name | Description |
|------|-------------|
| docker_image_uri | The ECR Docker image URI used to deploy Lambda Function |

## Features

### Docker Image Building

The module handles the Docker build process by:
- Creating a Docker image from the provided source code
- Building for the linux/amd64 platform (compatible with AWS Lambda)
- Tracking changes to source files to trigger rebuilds when needed

### ECR Repository Management

- Creates an ECR repository with the naming pattern: `{product_alias}-{env_alias}-{module_name}`
- Implements a lifecycle policy that keeps only the most recent 30 images
- Automatically handles authentication to the ECR repository

## Notes

- The source path should point to a directory containing a valid Dockerfile
- The module automatically tracks changes to source files and rebuilds the image when changes are detected
- The module does not handle Lambda function creation - use the returned image URI with a Lambda function module