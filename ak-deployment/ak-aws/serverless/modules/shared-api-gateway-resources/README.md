# Shared API Gateway Resources Module

## Overview

This module provides shared resources for both REST and WebSocket API Gateways in the Agent Kernel AWS serverless deployment. It eliminates resource conflicts and reduces infrastructure complexity by providing a single source of truth for API Gateway resources, primarily focusing on CloudWatch logging infrastructure.

## Problem Solved

Previously, both API Gateway modules created separate CloudWatch logging infrastructure:
- **API Gateway module**: Created `aws_iam_role.cloudwatch` + `aws_api_gateway_account.api_gateway` 
- **WebSocket API Gateway module**: Created `aws_iam_role.apigateway_cloudwatch_logs` + `aws_api_gateway_account.this`

This caused:
1. **Resource conflicts** - `aws_api_gateway_account` is a singleton per AWS account
2. **Duplicate infrastructure** - Two identical IAM roles doing the same job
3. **Resource waste** - Unnecessary duplication of roles and policies

## Solution

This shared module provides:
- **Single IAM role** for all API Gateway logging
- **Single `aws_api_gateway_account`** resource (singleton per account)
- **Shared permissions** that work for both REST and WebSocket APIs
- **Clean separation** with API Gateway module owning the shared resources

## Resources Created

- `aws_iam_role.cloudwatch` - Shared IAM role for API Gateway CloudWatch integration
- `aws_iam_role_policy.cloudwatch` - IAM policy with CloudWatch logging permissions
- `aws_api_gateway_account.api_gateway` - Account-level API Gateway configuration

## Usage

```hcl
module "shared_api_gateway_resources" {
  source = "./modules/shared-api-gateway-resources"

  product_alias = var.product_alias
  env_alias     = var.env_alias
  tags          = var.tags
}
```

## Outputs

- `cloudwatch_role_arn` - ARN of the shared CloudWatch IAM role
- `cloudwatch_role_id` - ID of the shared CloudWatch IAM role  
- `cloudwatch_role_name` - Name of the shared CloudWatch IAM role

## Integration

The shared role ARN is passed to both API Gateway modules via the `shared_cloudwatch_role_arn` variable, ensuring both REST and WebSocket APIs use the same CloudWatch logging infrastructure.
