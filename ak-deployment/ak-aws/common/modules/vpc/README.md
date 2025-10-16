# VPC Module

A Terraform module for creating production-ready AWS VPC infrastructure with public and private subnets, NAT gateway, and optimized routing for serverless applications.

## 📋 Overview

This module provisions a complete VPC networking stack following AWS best practices:

- 🌐 **Complete VPC**: DNS support, hostnames, and CIDR configuration
- 🔒 **Private Subnets**: Isolated subnets for Lambda functions and databases
- 🌍 **Public Subnets**: Internet-accessible subnets for NAT gateways
- 🚪 **NAT Gateway**: Secure outbound internet access for private resources
- 🛣️ **Route Tables**: Separate routing for public and private traffic
- 🔐 **Security Groups**: Pre-configured Lambda security group with egress rules
- 📍 **Multi-AZ**: Dynamic availability zone selection for high availability

Perfect for serverless architectures, Lambda functions requiring VPC access, Redis/RDS instances, and any workload needing network isolation.

## 📋 Requirements

| Name | Version |
|------|---------|
| Terraform | >= 1.9.5 |
| AWS Provider | >= 6.11.0 |

## 🚀 Usage

### Basic Example

```hcl
module "vpc" {
  source = "app.terraform.io/yaalalabs/ak-aws-common/aws//modules/vpc"

  vpc_cidr             = "10.0.0.0/16"
  public_subnet_cidrs  = ["10.0.1.0/24", "10.0.2.0/24"]
  private_subnet_cidrs = ["10.0.3.0/24", "10.0.4.0/24"]
  product_alias        = "myapp"
  env_alias            = "prod"
  
  tags = {
    Environment = "production"
    ManagedBy   = "terraform"
  }
}
```

### Complete Serverless Stack

```hcl
module "vpc" {
  source = "app.terraform.io/yaalalabs/ak-aws-common/aws//modules/vpc"

  vpc_cidr             = "10.0.0.0/16"
  public_subnet_cidrs  = ["10.0.1.0/24", "10.0.2.0/24"]
  private_subnet_cidrs = ["10.0.3.0/24", "10.0.4.0/24"]
  product_alias        = "myapp"
  env_alias            = "prod"
}

# Lambda function using VPC
resource "aws_lambda_function" "api" {
  function_name = "myapp-api"
  role          = aws_iam_role.lambda_role.arn
  
  vpc_config {
    subnet_ids         = module.vpc.private_subnet_ids
    security_group_ids = [module.vpc.lambda_security_group_id]
  }
}

# Redis cluster in private subnets
module "redis" {
  source = "app.terraform.io/yaalalabs/ak-aws-common/aws//modules/redis"

  product_alias = "myapp"
  env_alias     = "prod"
  vpc_id        = module.vpc.vpc_id
  subnet_ids    = module.vpc.private_subnet_ids
}
```

### Multi-Region Deployment

```hcl
# US-West-2 VPC
module "vpc_us_west" {
  source = "app.terraform.io/yaalalabs/ak-aws-common/aws//modules/vpc"

  vpc_cidr             = "10.0.0.0/16"
  public_subnet_cidrs  = ["10.0.1.0/24", "10.0.2.0/24"]
  private_subnet_cidrs = ["10.0.3.0/24", "10.0.4.0/24"]
  product_alias        = "myapp"
  env_alias            = "prod-us-west"
  
  tags = {
    Region = "us-west-2"
  }
}

# EU-West-1 VPC
module "vpc_eu_west" {
  source = "app.terraform.io/yaalalabs/ak-aws-common/aws//modules/vpc"

  vpc_cidr             = "10.1.0.0/16"
  public_subnet_cidrs  = ["10.1.1.0/24", "10.1.2.0/24"]
  private_subnet_cidrs = ["10.1.3.0/24", "10.1.4.0/24"]
  product_alias        = "myapp"
  env_alias            = "prod-eu-west"
  
  tags = {
    Region = "eu-west-1"
  }
}
```


## 📥 Inputs

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|:--------:|
| `vpc_cidr` | CIDR block for the VPC | `string` | `"10.0.0.0/16"` | no |
| `public_subnet_cidrs` | List of CIDR blocks for public subnets | `list(string)` | `["10.0.1.0/24", "10.0.2.0/24"]` | no |
| `private_subnet_cidrs` | List of CIDR blocks for private subnets | `list(string)` | `["10.0.3.0/24", "10.0.4.0/24"]` | no |
| `product_alias` | Short identifier for the product (e.g., "myapp") | `string` | n/a | yes |
| `env_alias` | Environment identifier (e.g., "dev", "staging", "prod") | `string` | n/a | yes |
| `tags` | Additional tags to apply to all resources | `map(string)` | `{}` | no |

## 📤 Outputs

| Name | Description | Example |
|------|-------------|---------|
| `vpc_id` | The ID of the VPC | `vpc-0abc123def456789` |
| `vpc_cidr_block` | CIDR block of the VPC | `10.0.0.0/16` |
| `public_subnet_ids` | List of public subnet IDs | `["subnet-abc123", "subnet-def456"]` |
| `private_subnet_ids` | List of private subnet IDs | `["subnet-789abc", "subnet-012def"]` |
| `nat_gateway_id` | ID of the NAT Gateway | `nat-0abc123def456789` |
| `nat_gateway_public_ip` | Elastic IP of the NAT Gateway | `52.12.34.56` |
| `internet_gateway_id` | ID of the Internet Gateway | `igw-0abc123def456789` |
| `lambda_security_group_id` | Security group ID for Lambda functions | `sg-0abc123def456789` |
| `public_route_table_id` | ID of the public route table | `rtb-0abc123def456789` |
| `private_route_table_id` | ID of the private route table | `rtb-0xyz789abc123def` |
| `availability_zones` | List of AZs used for subnets | `["us-west-2a", "us-west-2b"]` |

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    VPC (10.0.0.0/16)                            │
│                                                                 │
│  ┌────────────────────────┐    ┌───────────────────────────┐  │
│  │   Public Subnets       │    │   Private Subnets         │  │
│  │   (10.0.1.0/24, etc)   │    │   (10.0.3.0/24, etc)      │  │
│  │                        │    │                           │  │
│  │  ┌─────────────────┐  │    │  ┌────────────────────┐  │  │
│  │  │  NAT Gateway    │  │    │  │  Lambda Functions  │  │  │
│  │  │  (EIP attached) │  │    │  │                    │  │  │
│  │  └────────┬────────┘  │    │  └─────────┬──────────┘  │  │
│  │           │            │    │            │              │  │
│  │           │            │◄───┼────────────┘              │  │
│  │  ┌────────▼────────┐  │    │  (Route: 0.0.0.0/0 →     │  │
│  │  │ Internet Gateway│  │    │   NAT Gateway)            │  │
│  │  └────────┬────────┘  │    │                           │  │
│  └───────────┼────────────┘    │  ┌────────────────────┐  │  │
│              │                 │  │  Redis / RDS       │  │  │
│              │                 │  │  (ElastiCache)     │  │  │
└──────────────┼─────────────────┴──┴────────────────────────┴──┘
               │
               ▼
          Internet
```

## ✨ Features

### 🌐 VPC Configuration

- **DNS Support**: Enabled for hostname resolution
- **DNS Hostnames**: Enabled for public DNS names
- **CIDR Block**: Customizable, defaults to `10.0.0.0/16`
- **Tagging**: Automatic tagging with product and environment

### 🔒 Network Isolation

**Public Subnets**:
- Direct route to Internet Gateway
- Host NAT Gateway for private subnet internet access
- Suitable for load balancers and bastion hosts

**Private Subnets**:
- No direct internet access
- Outbound traffic routes through NAT Gateway
- Ideal for Lambda, Redis, RDS, and application servers

### 🚪 Gateway Management

**Internet Gateway**:
- Provides internet connectivity for public subnets
- Automatically attached to VPC

**NAT Gateway**:
- Deployed in first public subnet
- Uses Elastic IP for static outbound address
- Enables private resources to access internet
- High availability within single AZ

### 🔐 Security Groups

**Lambda Security Group**:
- Allows all outbound traffic (0.0.0.0/0:443, 80, etc.)
- No inbound rules by default (can be customized)
- Attachable to Lambda functions and other resources

## 🎯 Best Practices

### CIDR Planning

1. **Non-Overlapping CIDRs**: Ensure VPC CIDRs don't overlap if using VPC peering
2. **Subnet Sizing**: Plan subnet sizes based on expected resource count
3. **Future Growth**: Leave room for additional subnets

```hcl
# Good CIDR allocation for scalability
module "vpc" {
  vpc_cidr             = "10.0.0.0/16"     # 65,536 IPs
  public_subnet_cidrs  = [
    "10.0.0.0/24",   # 256 IPs per AZ
    "10.0.1.0/24"
  ]
  private_subnet_cidrs = [
    "10.0.10.0/23",  # 512 IPs per AZ for growth
    "10.0.12.0/23"
  ]
}
```

### High Availability

For production environments, consider deploying NAT Gateways in multiple AZs:

```hcl
# Note: This module deploys a single NAT Gateway
# For HA, you would need to extend the module or deploy manually
# in each AZ with separate private route tables
```

### Cost Optimization

1. **Single NAT Gateway**: Default configuration (cost-effective)
2. **Multi-AZ NAT**: For high availability (higher cost)
3. **VPC Endpoints**: Use for AWS services to avoid NAT Gateway data charges

## 💰 Cost Considerations

| Resource | Cost Component | Approximate Cost |
|----------|---------------|------------------|
| NAT Gateway | Hourly charge | ~$0.045/hour (~$32/month) |
| NAT Gateway | Data processing | $0.045/GB |
| Elastic IP | When not attached | $0.005/hour |
| VPC, Subnets, IGW | No charge | Free |

**Cost Savings Tips**:
- Use VPC endpoints for S3, DynamoDB to avoid NAT data charges
- For dev environments, consider alternatives to NAT Gateway
- Monitor data transfer through CloudWatch

## 🔍 Common Use Cases

### Lambda with Internet Access

```hcl
module "vpc" {
  source = "app.terraform.io/yaalalabs/ak-aws-common/aws//modules/vpc"
  
  product_alias = "myapp"
  env_alias     = "prod"
}

resource "aws_lambda_function" "api" {
  function_name = "api"
  
  vpc_config {
    subnet_ids         = module.vpc.private_subnet_ids
    security_group_ids = [module.vpc.lambda_security_group_id]
  }
  
  # Lambda can now access:
  # - Private resources (Redis, RDS) directly
  # - Internet via NAT Gateway
  # - AWS services via VPC endpoints (if configured)
}
```

### Database in Private Subnet

```hcl
resource "aws_db_subnet_group" "main" {
  name       = "myapp-db-subnet-group"
  subnet_ids = module.vpc.private_subnet_ids
}

resource "aws_db_instance" "postgres" {
  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.db_sg.id]
  
  # Database is isolated in private subnet
  # Only accessible from within VPC
}
```

## 🔍 Troubleshooting

### Lambda Cannot Access Internet

**Issue**: Lambda function in VPC cannot reach external APIs
```
Error: Connection timeout
```

**Solutions**:
1. Verify Lambda is in **private** subnets (not public)
2. Check NAT Gateway is running and has Elastic IP
3. Verify private route table has route to NAT Gateway:
   ```bash
   aws ec2 describe-route-tables --route-table-ids <private-rt-id>
   # Should show: 0.0.0.0/0 → nat-gateway-id
   ```

### Security Group Blocking Traffic

**Issue**: Resources cannot communicate
```
Error: Connection refused
```

**Solution**: Update security group rules:
```hcl
resource "aws_security_group_rule" "allow_redis" {
  type                     = "ingress"
  from_port                = 6379
  to_port                  = 6379
  protocol                 = "tcp"
  security_group_id        = aws_security_group.redis_sg.id
  source_security_group_id = module.vpc.lambda_security_group_id
}
```

### High NAT Gateway Costs

**Issue**: Unexpectedly high NAT Gateway charges

**Solutions**:
1. **Use VPC Endpoints** for AWS services:
   ```hcl
   resource "aws_vpc_endpoint" "s3" {
     vpc_id       = module.vpc.vpc_id
     service_name = "com.amazonaws.${var.region}.s3"
     route_table_ids = [module.vpc.private_route_table_id]
   }
   ```

2. **Monitor Data Transfer**:
   ```bash
   aws cloudwatch get-metric-statistics \
     --namespace AWS/NATGateway \
     --metric-name BytesOutToSource \
     --dimensions Name=NatGatewayId,Value=<nat-id>
   ```

## 📚 Additional Resources

- [AWS VPC Documentation](https://docs.aws.amazon.com/vpc/)
- [NAT Gateway Pricing](https://aws.amazon.com/vpc/pricing/)
- [Lambda VPC Networking](https://docs.aws.amazon.com/lambda/latest/dg/configuration-vpc.html)
- [VPC Endpoints](https://docs.aws.amazon.com/vpc/latest/privatelink/vpc-endpoints.html)

## 🔗 Related Modules

- [Redis Module](../redis/) - Deploy Redis in private subnets
- [ECR Module](../ecr/) - For containerized Lambda functions

---

**Note**: This module creates a single NAT Gateway in the first availability zone. For production high-availability requirements, consider deploying NAT Gateways in multiple AZs with corresponding route table adjustments.