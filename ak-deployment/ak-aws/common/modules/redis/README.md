# Redis Module

A Terraform module for deploying Amazon ElastiCache Redis clusters in AWS VPC infrastructure with secure networking and best-practice configurations.

## 📋 Overview

This module provisions a fully-managed Redis cluster using AWS ElastiCache:

- ⚡ **ElastiCache Redis**: Managed Redis service with automatic failover
- 🔒 **VPC Isolation**: Deployed in private subnets with security groups
- 🌐 **Network Security**: Configurable access controls and port settings
- 📈 **Scalable**: Configurable node types and cluster size
- 🏷️ **Tagging**: Standardized resource tagging for management
- 🔄 **High Performance**: In-memory caching with sub-millisecond latency

Perfect for session storage, application caching, real-time analytics, pub/sub messaging, and serverless Lambda state management.

## 📋 Requirements

| Name | Version |
|------|---------|
| Terraform | >= 1.9.5 |
| AWS Provider | >= 6.11.0 |

## 🚀 Usage

### Basic Example

```hcl
module "redis" {
  source = "app.terraform.io/yaalalabs/ak-aws-common/aws//modules/redis"

  product_alias = "myapp"
  env_alias     = "prod"
  module_name   = "cache"
  
  vpc_id        = module.vpc.vpc_id
  vpc_cidr      = "10.0.0.0/16"
  subnet_ids    = module.vpc.private_subnet_ids
  
  port          = 6379
  node_type     = "cache.t3.micro"
  node_count    = 1
  
  tags = {
    Environment = "production"
    Purpose     = "session-cache"
  }
}
```

### Production Setup with Lambda Integration

```hcl
# VPC for networking
module "vpc" {
  source = "app.terraform.io/yaalalabs/ak-aws-common/aws//modules/vpc"

  product_alias = "myapp"
  env_alias     = "prod"
  vpc_cidr      = "10.0.0.0/16"
}

# Redis cluster in private subnets
module "redis" {
  source = "app.terraform.io/yaalalabs/ak-aws-common/aws//modules/redis"

  product_alias = "myapp"
  env_alias     = "prod"
  module_name   = "session"
  
  vpc_id     = module.vpc.vpc_id
  vpc_cidr   = module.vpc.vpc_cidr_block
  subnet_ids = module.vpc.private_subnet_ids
  
  node_type  = "cache.r6g.large"
  node_count = 2
  
  tags = {
    Environment = "production"
    Backup      = "daily"
  }
}

# Lambda function using Redis
resource "aws_lambda_function" "api" {
  function_name = "myapp-api"
  
  vpc_config {
    subnet_ids         = module.vpc.private_subnet_ids
    security_group_ids = [module.vpc.lambda_security_group_id]
  }
  
  environment {
    variables = {
      REDIS_URL = module.redis.url
    }
  }
}
```

### Multi-Environment Deployment

```hcl
# Development environment (smaller, cost-optimized)
module "redis_dev" {
  source = "app.terraform.io/yaalalabs/ak-aws-common/aws//modules/redis"

  product_alias = "myapp"
  env_alias     = "dev"
  module_name   = "cache"
  
  vpc_id     = module.vpc_dev.vpc_id
  vpc_cidr   = module.vpc_dev.vpc_cidr_block
  subnet_ids = module.vpc_dev.private_subnet_ids
  
  node_type  = "cache.t3.micro"  # Cost-effective for dev
  node_count = 1
}

# Production environment (larger, high-performance)
module "redis_prod" {
  source = "app.terraform.io/yaalalabs/ak-aws-common/aws//modules/redis"

  product_alias = "myapp"
  env_alias     = "prod"
  module_name   = "cache"
  
  vpc_id     = module.vpc_prod.vpc_id
  vpc_cidr   = module.vpc_prod.vpc_cidr_block
  subnet_ids = module.vpc_prod.private_subnet_ids
  
  node_type  = "cache.r6g.xlarge"  # High-performance for prod
  node_count = 3
  
  tags = {
    BusinessUnit = "Engineering"
    CostCenter   = "Infrastructure"
  }
}
```

## 📥 Inputs

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|:--------:|
| `product_alias` | Short identifier for the product (e.g., "myapp") | `string` | n/a | yes |
| `env_alias` | Environment identifier (e.g., "dev", "staging", "prod") | `string` | n/a | yes |
| `module_name` | Module/service name for resource identification | `string` | n/a | yes |
| `vpc_id` | VPC ID where Redis will be deployed | `string` | n/a | yes |
| `vpc_cidr` | CIDR block of the VPC (for security group rules) | `string` | n/a | yes |
| `subnet_ids` | List of private subnet IDs for Redis deployment | `list(string)` | n/a | yes |
| `port` | Redis port number | `number` | `6379` | no |
| `node_type` | ElastiCache node instance type | `string` | `"cache.t3.micro"` | no |
| `node_count` | Number of cache nodes in the cluster | `number` | `1` | no |
| `tags` | Additional tags to apply to resources | `map(string)` | `{}` | no |

## 📤 Outputs

| Name | Description | Example |
|------|-------------|---------|
| `url` | Redis connection URL | `redis://myapp-prod-cache-redis.abc123.0001.usw2.cache.amazonaws.com:6379` |
| `cluster_id` | ElastiCache cluster identifier | `myapp-prod-cache-redis` |
| `endpoint` | Redis cluster endpoint address | `myapp-prod-cache-redis.abc123.0001.usw2.cache.amazonaws.com` |
| `port` | Redis cluster port | `6379` |
| `security_group_id` | Security group ID for Redis cluster | `sg-0abc123def456789` |

## ✨ Features

### 🔒 Security Configuration

- **VPC Deployment**: Redis deployed in private subnets only
- **Security Group**: Automatic security group with restricted ingress
- **Network Isolation**: Access limited to VPC CIDR range
- **No Public Access**: Cluster not accessible from internet

### ⚙️ Cluster Configuration

- **Naming Convention**: `{product_alias}-{env_alias}-{module_name}-redis`
- **Parameter Group**: Uses `default.redis7` parameter group
- **Subnet Group**: Automatic subnet group creation for multi-AZ
- **Flexible Sizing**: Configurable node types and cluster size

### 📊 Node Types & Sizing

| Node Type | vCPU | Memory | Use Case |
|-----------|------|--------|----------|
| `cache.t3.micro` | 2 | 0.5 GB | Dev/Test |
| `cache.t3.small` | 2 | 1.37 GB | Small workloads |
| `cache.t3.medium` | 2 | 3.09 GB | Medium workloads |
| `cache.r6g.large` | 2 | 13.07 GB | Production |
| `cache.r6g.xlarge` | 4 | 26.32 GB | High-performance |
| `cache.r6g.2xlarge` | 8 | 52.82 GB | Large datasets |

## 🎯 Best Practices

### 1. Use Appropriate Node Types

```hcl
# Development: Cost-optimized
node_type = "cache.t3.micro"

# Production: Performance-optimized
node_type = "cache.r6g.large"  # Graviton2-based for better price/performance
```

### 2. Multi-Node for High Availability

```hcl
# Single node for dev
node_count = 1

# Multiple nodes for production resilience
node_count = 2  # or 3 for better distribution
```

### 3. Security Group Management

The module creates a security group allowing Redis access from the VPC CIDR. For more granular control, consider modifying the security group after deployment:

```hcl
resource "aws_security_group_rule" "lambda_to_redis" {
  type                     = "ingress"
  from_port                = 6379
  to_port                  = 6379
  protocol                 = "tcp"
  security_group_id        = module.redis.security_group_id
  source_security_group_id = module.vpc.lambda_security_group_id
  description              = "Allow Lambda access to Redis"
}
```

### 4. Monitoring and Alerts

```hcl
resource "aws_cloudwatch_metric_alarm" "redis_cpu" {
  alarm_name          = "${var.product_alias}-${var.env_alias}-redis-cpu"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "CPUUtilization"
  namespace           = "AWS/ElastiCache"
  period              = 300
  statistic           = "Average"
  threshold           = 75
  
  dimensions = {
    CacheClusterId = module.redis.cluster_id
  }
}
```

## 💰 Cost Optimization

1. **Right-Size Nodes**: Start with smaller nodes and scale up based on metrics
2. **Use Graviton Instances**: R6g instances offer better price/performance
3. **Development Environments**: Use t3.micro for non-production
4. **Reserved Nodes**: Consider reserved instances for production (1-3 year terms)

### Approximate Monthly Costs (US-West-2)

| Node Type | Hourly | Monthly (~730 hrs) |
|-----------|--------|-------------------|
| cache.t3.micro | $0.017 | ~$12 |
| cache.t3.small | $0.034 | ~$25 |
| cache.r6g.large | $0.151 | ~$110 |
| cache.r6g.xlarge | $0.302 | ~$220 |

## 📝 Common Use Cases

### Session Storage for Web Applications

```hcl
module "session_cache" {
  source = "app.terraform.io/yaalalabs/ak-aws-common/aws//modules/redis"

  product_alias = "webapp"
  env_alias     = "prod"
  module_name   = "session"
  
  vpc_id     = module.vpc.vpc_id
  vpc_cidr   = module.vpc.vpc_cidr_block
  subnet_ids = module.vpc.private_subnet_ids
  
  node_type  = "cache.r6g.large"
  node_count = 2
}
```

### API Rate Limiting & Caching

```hcl
module "api_cache" {
  source = "app.terraform.io/yaalalabs/ak-aws-common/aws//modules/redis"

  product_alias = "api"
  env_alias     = "prod"
  module_name   = "ratelimit"
  
  vpc_id     = module.vpc.vpc_id
  vpc_cidr   = module.vpc.vpc_cidr_block
  subnet_ids = module.vpc.private_subnet_ids
  
  node_type = "cache.r6g.xlarge"
}
```

### Real-Time Analytics

```hcl
module "analytics_cache" {
  source = "app.terraform.io/yaalalabs/ak-aws-common/aws//modules/redis"

  product_alias = "analytics"
  env_alias     = "prod"
  module_name   = "realtime"
  
  vpc_id     = module.vpc.vpc_id
  vpc_cidr   = module.vpc.vpc_cidr_block
  subnet_ids = module.vpc.private_subnet_ids
  
  node_type  = "cache.r6g.2xlarge"
  node_count = 3
}
```

## 🔍 Troubleshooting

### Cannot Connect to Redis

**Issue**: Application cannot connect to Redis
```
Error: Connection refused / timeout
```

**Solutions**:
1. **Check Security Groups**: Ensure security group allows traffic on port 6379
   ```bash
   aws ec2 describe-security-groups --group-ids <sg-id>
   ```

2. **Verify VPC Configuration**: Application must be in same VPC
3. **Check Redis Status**:
   ```bash
   aws elasticache describe-cache-clusters --cache-cluster-id <cluster-id>
   ```

### Redis Performance Issues

**Issue**: Slow response times or high latency

**Solutions**:
1. **Check CPU Utilization**:
   ```bash
   aws cloudwatch get-metric-statistics \
     --namespace AWS/ElastiCache \
     --metric-name CPUUtilization \
     --dimensions Name=CacheClusterId,Value=<cluster-id>
   ```

2. **Monitor Memory**: Ensure not approaching memory limit
3. **Scale Up**: Upgrade to larger node type or add nodes
4. **Review Queries**: Optimize application Redis usage patterns

### Connection Limit Exceeded

**Issue**: Too many connections to Redis
```
Error: max number of clients reached
```

**Solution**: Implement connection pooling in application:
```python
# Python example
import redis
pool = redis.ConnectionPool(
    host='redis-endpoint',
    port=6379,
    max_connections=50
)
redis_client = redis.Redis(connection_pool=pool)
```

## 📚 Additional Resources

- [AWS ElastiCache for Redis Documentation](https://docs.aws.amazon.com/elasticache/latest/red-ug/)
- [Redis Best Practices](https://redis.io/docs/management/optimization/)
- [ElastiCache Pricing](https://aws.amazon.com/elasticache/pricing/)
- [Choosing Node Types](https://docs.aws.amazon.com/AmazonElastiCache/latest/red-ug/CacheNodes.SupportedTypes.html)

## 🔗 Related Modules

- [VPC Module](../vpc/) - Required for Redis networking
- [Lambda Package Module](../lambda-package/) - For deploying Lambda functions that use Redis

---

**Note**: This module currently uses Redis 7 with the default parameter group. Future versions will support SSL/TLS encryption and custom parameter groups for advanced configurations.

