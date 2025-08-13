# Terraform Module: lambda-package

A Terraform module for managing AWS Lambda function and layer deployment packages in S3.

## Overview

This module simplifies the process of managing Lambda deployment packages by:

- Uploading Lambda function or layer ZIP packages to S3
- Creating a consistent S3 key structure for organizing packages
- Handling package versioning through file checksums
- Supporting both new uploads and referencing existing packages

The module is designed for Agent Kernel deployments but can be used for any Lambda function or layer package management.

## Requirements

| Name | Version |
|------|---------|
| terraform | >= 1.9.5 |
| aws | 6.7.0 |

## Usage

```hcl
module "lambda_package" {
  source  = "app.terraform.io/yaalalabs/ak-lambda-package/aws"
  version = "0.0.1"

  region              = "us-west-2"
  product_alias       = "myproduct"
  env_alias           = "dev"
  module_name         = "api"
  package_dir_path    = "path/to/function.zip"
  s3_bucket           = "my-lambda-packages-bucket"
  is_layer            = false
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
| package_dir_path | Path to the Lambda function or layer ZIP package | `string` | n/a | yes |
| is_layer | Whether the package is a Lambda layer | `bool` | false | no |
| s3_bucket | S3 bucket name where packages will be stored | `string` | n/a | yes |

## Features

### S3 Package Management

The module handles Lambda package management by:
- Uploading ZIP packages to a specified S3 bucket
- Creating a structured S3 key path: `{product_alias}/{region}/{env_alias}/{module_name}/{package_type}/{filename}`
- Using file checksums (etag) to detect changes and trigger updates

### Package Type Support

- Supports both Lambda function packages (`is_layer = false`)
- Supports Lambda layer packages (`is_layer = true`)

## Notes

- The S3 bucket must exist before using this module
- The module does not create the ZIP package - it only handles uploading to S3
- If the package file doesn't exist locally, the module will reference an existing object in S3
- Use the S3 object created by this module as the source for your Lambda function or layer