# Memorystore Module

A Terraform module for deploying Google Memorystore for Redis with VPC integration, AUTH support, and transit encryption.

## Overview

This module provisions a fully-managed Redis instance using Google Memorystore:

- **Managed Redis**: Google-managed Redis 7.0 with automatic patching
- **VPC Isolation**: Deployed inside your VPC for secure access
- **AUTH Enabled**: Password-based authentication for security
- **Transit Encryption**: TLS encryption for data in transit
- **Flexible Tiers**: BASIC (dev) or STANDARD_HA (production)

Perfect for session storage, application caching, real-time analytics, and agent state management.

## Requirements

| Name | Version |
|------|---------|
| Terraform | >= 1.9.5 |
| Google Provider | >= 6.8.0 |

## Usage

### Basic Example

```hcl
module "redis" {
  source = "../common/modules/memorystore"
  # source = "yaalalabs/ak-common/google//modules/memorystore"  # uncomment for registry

  project_id    = "my-gcp-project"
  region        = "us-central1"
  product_alias = "myapp"
  env_alias     = "prod"
  module_name   = "cache"
  network_id    = module.vpc.network_id
}
```

### Production Setup with High Availability

```hcl
module "redis" {
  source = "../common/modules/memorystore"
  # source = "yaalalabs/ak-common/google//modules/memorystore"  # uncomment for registry

  project_id     = var.project_id
  region         = var.region
  product_alias  = var.product_alias
  env_alias      = "prod"
  module_name    = "session"
  network_id     = module.vpc.network_id

  tier           = "STANDARD_HA"  # High availability with replica
  memory_size_gb = 4
  auth_enabled   = true

  tags = {
    environment = "production"
    purpose     = "session-cache"
  }
}
```

### With Cloud Run

```hcl
module "vpc" {
  source = "../common/modules/vpc"
  # ...
}

module "redis" {
  source = "../common/modules/memorystore"

  project_id    = var.project_id
  region        = var.region
  product_alias = var.product_alias
  env_alias     = var.env_alias
  module_name   = var.module_name
  network_id    = module.vpc.network_id
}

# Cloud Run uses redis URL via environment variable
# AK_SESSION__REDIS__URL = module.redis.url
```

## Inputs

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|:--------:|
| `project_id` | GCP project ID | `string` | n/a | yes |
| `region` | GCP region | `string` | `"us-central1"` | no |
| `product_alias` | Short identifier for the product | `string` | n/a | yes |
| `env_alias` | Environment identifier | `string` | n/a | yes |
| `module_name` | Module name for resource identification | `string` | n/a | yes |
| `network_id` | VPC network ID for the Redis instance | `string` | n/a | yes |
| `tier` | Service tier: BASIC or STANDARD_HA | `string` | `"BASIC"` | no |
| `memory_size_gb` | Redis memory size in GB | `number` | `1` | no |
| `redis_version` | Redis version | `string` | `"REDIS_7_0"` | no |
| `auth_enabled` | Enable Redis AUTH password | `bool` | `true` | no |
| `tags` | Resource labels | `map(string)` | `{}` | no |

## Outputs

| Name | Description | Example |
|------|-------------|---------|
| `host` | Redis instance hostname | `10.0.0.3` |
| `port` | Redis instance port | `6379` |
| `url` | Redis connection URL | `redis://10.0.0.3:6379` |
| `auth_string` | Redis AUTH password (sensitive) | `auto-generated-password` |
| `full_redis_url` | Redis URL with auth included (sensitive) | `rediss://:password@10.0.0.3:6379` |

## Features

### Service Tiers

| Tier | Description | Use Case |
|------|-------------|----------|
| `BASIC` | Single node, no replication | Development, testing |
| `STANDARD_HA` | Primary + replica with automatic failover | Production |

### Memory Sizes

| Size | Use Case |
|------|----------|
| 1 GB | Small apps, dev environments |
| 2-4 GB | Medium workloads |
| 5-16 GB | Large production datasets |
| Up to 300 GB | Enterprise scale |

### Security

- **AUTH**: Password required for connections (enabled by default)
- **Transit Encryption**: TLS via `SERVER_AUTHENTICATION` mode
- **VPC Only**: Redis is only accessible from within the VPC
- **No Public IP**: Cannot be reached from the internet

## GCP vs AWS Comparison

| GCP (Memorystore) | AWS (ElastiCache) |
|--------------------|-------------------|
| `google_redis_instance` (1 resource) | Cluster + Subnet Group + Parameter Group (3 resources) |
| VPC via `authorized_network` | VPC via subnet group + security group |
| Built-in AUTH | AUTH via parameter group |
| Built-in TLS | TLS via parameter group |
| BASIC / STANDARD_HA tiers | Single node / Cluster mode |

**Key difference**: GCP Memorystore is 1 resource. AWS ElastiCache needs 3+ resources for the same setup.

## Cost Considerations

### Approximate Monthly Costs (us-central1)

| Tier | Memory | Monthly Cost |
|------|--------|-------------|
| BASIC | 1 GB | ~$35 |
| BASIC | 4 GB | ~$140 |
| STANDARD_HA | 1 GB | ~$70 |
| STANDARD_HA | 4 GB | ~$280 |

**Cost Tips**:
1. Use BASIC tier for dev/staging
2. Start with 1 GB and scale up based on usage
3. Monitor memory usage in Cloud Monitoring

## Troubleshooting

### Cannot Connect to Redis

1. Verify VPC Connector is active and in the same network
2. Check the Redis instance is in `READY` state:
   ```bash
   gcloud redis instances describe myapp-dev-cache-redis --region=us-central1
   ```
3. Ensure your app uses the correct URL from `AK_SESSION__REDIS__URL`
4. For TLS connections, use `rediss://` (double s) protocol

### High Memory Usage

```bash
# Check memory usage
gcloud redis instances describe myapp-dev-cache-redis --region=us-central1 \
  --format="value(memorySizeGb)"
```

Increase `memory_size_gb` in your Terraform config and apply.

## Related Modules

- [VPC Module](../vpc/) - Required for Redis networking
- [Artifact Registry Module](../artifact-registry/) - For Docker images
- [Firestore Module](../firestore/) - Alternative session storage

---

**Note**: Memorystore Redis requires a VPC network. Always provide a valid `network_id` from the VPC module or an existing VPC.
