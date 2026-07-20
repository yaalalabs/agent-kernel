# Valkey Module

A Terraform module for deploying Amazon ElastiCache for Valkey clusters in AWS VPC infrastructure with secure networking and best-practice configurations.

Valkey is the open-source, Linux Foundation-governed fork of Redis. It is wire-compatible with Redis and available on AWS ElastiCache as a native engine at a lower price point than the Redis OSS engine.

## 📋 Overview

This module provisions a fully-managed Valkey cluster using AWS ElastiCache:

- ⚡ **ElastiCache for Valkey**: Managed Valkey service
- 🔒 **VPC Isolation**: Deployed in private subnets with security groups
- 🌐 **Network Security**: Configurable access controls and port settings
- 📈 **Scalable**: Configurable node types and cluster size
- 🏷️ **Tagging**: Standardized resource tagging for management

Perfect for session storage, response storage for async execution, and application caching.

## 📋 Requirements

| Name | Version |
|------|---------|
| Terraform | >= 1.9.5 |
| AWS Provider | >= 6.11.0 |

## 🚀 Usage

### Basic Example

```hcl
module "valkey" {
  source = "yaalalabs/ak-common/aws//modules/valkey"

  product_alias = "myapp"
  env_alias     = "prod"
  module_name   = "cache"

  vpc_id     = module.vpc.vpc_id
  vpc_cidr   = "10.0.0.0/16"
  subnet_ids = module.vpc.private_subnet_ids

  port       = 6379
  node_type  = "cache.t4g.micro"
  node_count = 1

  tags = {
    Environment = "production"
    Purpose     = "session-cache"
  }
}
```

### Overriding the engine version

`engine_version` and `parameter_group_name` **must move together**: the parameter group
family must match the engine major version. Overriding only one fails at `terraform apply`.

```hcl
module "valkey" {
  source = "yaalalabs/ak-common/aws//modules/valkey"

  product_alias = "myapp"
  env_alias     = "prod"
  module_name   = "cache"

  vpc_id     = module.vpc.vpc_id
  vpc_cidr   = module.vpc.vpc_cidr_block
  subnet_ids = module.vpc.private_subnet_ids

  # A 7.x engine requires the matching 7.x parameter group family.
  engine_version       = "7.2"
  parameter_group_name = "default.valkey7"
}
```

## 📥 Inputs

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|:--------:|
| `product_alias` | Short identifier for the product (e.g., "myapp") | `string` | n/a | yes |
| `env_alias` | Environment identifier (e.g., "dev", "staging", "prod") | `string` | n/a | yes |
| `module_name` | Module/service name for resource identification | `string` | n/a | yes |
| `vpc_id` | VPC ID where Valkey will be deployed | `string` | n/a | yes |
| `vpc_cidr` | CIDR block of the VPC (for security group rules) | `string` | n/a | yes |
| `subnet_ids` | List of private subnet IDs for Valkey deployment | `list(string)` | n/a | yes |
| `port` | Valkey port number | `number` | `6379` | no |
| `node_type` | ElastiCache node instance type | `string` | `"cache.t4g.micro"` | no |
| `node_count` | Number of cache nodes in the cluster | `number` | `1` | no |
| `engine_version` | Valkey engine version (must match `parameter_group_name` family) | `string` | `"8.0"` | no |
| `parameter_group_name` | ElastiCache parameter group name (family must match engine major version) | `string` | `"default.valkey8"` | no |
| `tags` | Additional tags to apply to resources | `map(string)` | `{}` | no |

## 📤 Outputs

| Name | Description | Example |
|------|-------------|---------|
| `url` | Valkey connection URL | `valkey://myapp-prod-cache-valkey.abc123.0001.usw2.cache.amazonaws.com:6379` |

## ✨ Features

### 🔒 Security Configuration

- **VPC Deployment**: Valkey deployed in private subnets only
- **Security Group**: Automatic security group with restricted ingress limited to the VPC CIDR
- **No Public Access**: Cluster not accessible from the internet
- **No IAM Required**: Access is network-level via the security group

### ⚙️ Cluster Configuration

- **Resource**: Provisioned as a cluster-mode-disabled `aws_elasticache_replication_group`
  (ElastiCache exposes the Valkey engine through the replication group resource;
  `aws_elasticache_cluster` only supports the `memcached` and `redis` engines). A single node
  (`node_count = 1`) yields the same single-primary topology as the Redis module.
- **Naming Convention**: `{product_alias}-{env_alias}-{module_name}-valkey`
- **Engine Version**: Configurable via `engine_version` (default `8.0`)
- **Parameter Group**: Configurable via `parameter_group_name` (default `default.valkey8`)
- **Subnet Group**: Automatic subnet group creation for multi-AZ
- **Flexible Sizing**: Configurable node types and cluster size (`node_count` maps to
  `num_cache_clusters` — primary plus replicas)

## 🔍 Troubleshooting

### `terraform apply` fails on parameter group family mismatch

The parameter group family must match the engine major version. If you override
`engine_version` to a 7.x version, you must also set `parameter_group_name = "default.valkey7"`
(and vice versa). Overriding only one of the two fails at apply time.

### Cannot Connect to Valkey

1. **Check Security Groups**: Ensure the security group allows traffic on `var.port` (default 6379).
2. **Verify VPC Configuration**: The client must be in the same VPC / reachable from the VPC CIDR.
3. **Check cluster status**:
   ```bash
   aws elasticache describe-cache-clusters --cache-cluster-id <cluster-id>
   ```

## 🔗 Related Modules

- [VPC Module](../vpc/) - Required for Valkey networking
- [Redis Module](../redis/) - Redis engine equivalent of this module

---

**Note**: This module uses the Valkey engine with the `default.valkey8` parameter group by
default. `engine_version` and `parameter_group_name` must be changed together so the parameter
group family matches the engine major version.
