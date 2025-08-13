# Terraform Module: s3

A Terraform module for creating and configuring secure S3 buckets for storing Lambda function source code and other resources.

## Overview

This module simplifies the process of creating secure S3 buckets by:

- Creating an S3 bucket with a standardized naming convention
- Implementing security best practices including blocking public access
- Configuring bucket policies to restrict access to authorized services
- Setting up versioning for production environments
- Enabling server-side encryption for enhanced security

The module is designed for Agent Kernel deployments but can be used for any application requiring secure S3 storage.

## Requirements

| Name | Version |
|------|---------|
| terraform | >= 1.9.5 |
| aws | 6.7.0 |

## Usage

```hcl
module "source_storage" {
  source  = "app.terraform.io/yaalalabs/ak-s3/aws"
  version = "0.0.1"
  region              = "us-west-2"
  product_alias       = "myproduct"
  env_alias           = "dev"
  product_display_name = "My Product"
  is_production       = false
}
```

## Inputs

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|:--------:|
| region | AWS region for deployment | `string` | n/a | yes |
| product_alias | Short name for the product | `string` | n/a | yes |
| env_alias | Environment name (dev, staging, prod) | `string` | n/a | yes |
| product_display_name | Human-readable product name | `string` | n/a | yes |
| is_production | Whether this is a production deployment | `bool` | n/a | yes |
| s3_bucket_tags | Additional tags to apply to the S3 bucket | `map(string)` | `{}` | no |
| s3_kms_key_id | KMS key ID for server-side encryption | `string` | `null` | no |

## Outputs

| Name | Description |
|------|-------------|
| source_storage_s3_bucket | The ID of the created S3 bucket |

## Features

### Bucket Configuration

- Creates an S3 bucket with the naming pattern: `{product_alias}-{env_alias}-sources-{account_id}`
- Applies tags for resource management including backup configuration
- Enables force_destroy to allow bucket deletion with Terraform

### Security Features

- Blocks all public access to the bucket
- Enforces SSL/TLS for all requests with a deny policy
- Restricts access to Lambda service for specific operations
- Enables versioning for production environments
- Configures KMS server-side encryption for production environments

## Notes

- For production deployments, set `is_production = true` to enable versioning and encryption
- To use KMS encryption, provide a valid KMS key ID via the `s3_kms_key_id` parameter
- The bucket is configured to allow Lambda functions to access objects, making it suitable for Lambda deployment packages