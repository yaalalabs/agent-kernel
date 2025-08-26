# VPC Module

This module creates a VPC with public and private subnets, a NAT gateway, and the necessary routing configuration to route Lambda's internet traffic through the NAT gateway instead of directly through an internet gateway.

## Features

- VPC with DNS support and hostnames enabled
- Public subnets for the NAT gateway
- Private subnets for Lambda functions
- Internet Gateway for public subnets
- NAT Gateway in a public subnet
- Route tables for both public and private subnets
- Security group for Lambda functions
- Dynamic availability zone selection

## Usage

```hcl
module "vpc" {
  source = "../modules/vpc"

  vpc_cidr            = "10.0.0.0/16"
  public_subnet_cidrs = ["10.0.1.0/24", "10.0.2.0/24"]
  private_subnet_cidrs = ["10.0.3.0/24", "10.0.4.0/24"]
  product_alias       = "my-product"
  env_alias           = "dev"
  tags                = {
    Environment = "development"
  }
}
```

## Inputs

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|:--------:|
| vpc_cidr | CIDR block for the VPC | `string` | `"10.0.0.0/16"` | no |
| public_subnet_cidrs | CIDR blocks for the public subnets | `list(string)` | `["10.0.1.0/24", "10.0.2.0/24"]` | no |
| private_subnet_cidrs | CIDR blocks for the private subnets | `list(string)` | `["10.0.3.0/24", "10.0.4.0/24"]` | no |
| product_alias | Product alias | `string` | n/a | yes |
| env_alias | Environment alias | `string` | n/a | yes |
| tags | Resource tags | `map(string)` | `{}` | no |

## Outputs

| Name | Description |
|------|-------------|
| vpc_id | The ID of the VPC |
| public_subnet_ids | List of IDs of public subnets |
| private_subnet_ids | List of IDs of private subnets |
| nat_gateway_id | ID of the NAT Gateway |
| internet_gateway_id | ID of the Internet Gateway |
| lambda_security_group_id | ID of the Lambda security group |
| public_route_table_id | ID of the public route table |
| private_route_table_id | ID of the private route table |

## Benefits of NAT Gateway

Using a NAT gateway for Lambda functions provides several benefits:

1. **Security**: Lambda functions in private subnets cannot be directly accessed from the internet
2. **Control**: All outbound traffic goes through a single point, making it easier to monitor and control
3. **IP Management**: All outbound requests use the NAT gateway's Elastic IP, simplifying IP allowlisting
4. **Reliability**: AWS-managed NAT gateway provides high availability and scalability

## Considerations

1. **Cost**: NAT gateways incur hourly charges and data processing fees
2. **High Availability**: For production environments, consider deploying NAT gateways in multiple availability zones
3. **Performance**: Monitor NAT gateway performance metrics to ensure it can handle the traffic volume