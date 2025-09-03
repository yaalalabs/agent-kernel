# Terraform Module: Redis

This module provisions Redis resources in AWS infrastructure.

## Prerequisites

- AWS provider configured
- Valid AWS credentials

## Input Variables

| Name               | Description                               | Type           | Default | Required |
|--------------------|-------------------------------------------|----------------|---------|:--------:|
| region             | AWS Region                                | `string`       | -       |   yes    |
| product_alias      | Product alias for naming                  | `string`       | -       |   yes    |
| env_alias          | Environment alias                         | `string`       | -       |   yes    |
| vpc_id             | VPC ID for Redis deployment               | `string`       | -       |   yes    |
| private_subnet_ids | List of private subnet IDs                | `list(string)` | -       |   yes    |
| port               | Redis port number                         | `number`       | `6379`  |    no    |
| tags               | Resource tags                             | `map(string)`  | `{}`    |    no    |

