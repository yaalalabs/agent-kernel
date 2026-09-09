# VPC Module

A Terraform module for creating production-ready GCP VPC infrastructure with public and private subnets, Cloud NAT, and firewall rules for serverless and containerized applications.

## Overview

This module provisions a complete VPC networking stack following GCP best practices:

- **Complete VPC**: Custom mode VPC with manually managed subnets
- **Private Subnets**: Isolated subnets for Cloud Functions, Cloud Run, and Redis with Private Google Access
- **Public Subnets**: Internet-accessible subnets for external-facing resources
- **Cloud NAT**: Secure outbound internet access for private resources via Cloud Router
- **Firewall Rules**: Internal traffic allowed between subnets, external traffic blocked by default

Perfect for serverless architectures, Cloud Functions requiring VPC access, Cloud Run services, Memorystore Redis, and any workload needing network isolation.

## Requirements

| Name | Version |
|------|---------|
| Terraform | >= 1.9.5 |
| Google Provider | >= 6.8.0 |

## Usage

### Basic Example

```hcl
module "vpc" {
  source = "../common/modules/vpc"
  # source = "yaalalabs/ak-common/google//modules/vpc"  # uncomment for registry

  project_id          = "my-gcp-project"
  region              = "us-central1"
  product_alias       = "myapp"
  env_alias           = "prod"
  public_subnet_cidr  = "10.0.1.0/24"
  private_subnet_cidr = "10.0.2.0/24"
}
```

### With Cloud Run Service

```hcl
module "vpc" {
  source = "../common/modules/vpc"
  # source = "yaalalabs/ak-common/google//modules/vpc"  # uncomment for registry

  project_id    = var.project_id
  region        = var.region
  product_alias = var.product_alias
  env_alias     = var.env_alias
}

# VPC Connector lets Cloud Run talk to private resources
resource "google_vpc_access_connector" "connector" {
  name          = "${var.product_alias}-${var.env_alias}-connector"
  project       = var.project_id
  region        = var.region
  network       = module.vpc.network_id
  ip_cidr_range = "10.8.0.0/28"
}
```

### With Memorystore Redis

```hcl
module "vpc" {
  source = "../common/modules/vpc"
  # source = "yaalalabs/ak-common/google//modules/vpc"  # uncomment for registry

  project_id    = var.project_id
  region        = var.region
  product_alias = var.product_alias
  env_alias     = var.env_alias
}

module "redis" {
  source = "../common/modules/memorystore"
  # source = "yaalalabs/ak-common/google//modules/memorystore"  # uncomment for registry

  project_id    = var.project_id
  region        = var.region
  product_alias = var.product_alias
  env_alias     = var.env_alias
  module_name   = "cache"
  network_id    = module.vpc.network_id
}
```

## Inputs

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|:--------:|
| `project_id` | GCP project ID | `string` | n/a | yes |
| `region` | GCP region | `string` | `"us-central1"` | no |
| `product_alias` | Short identifier for the product | `string` | n/a | yes |
| `env_alias` | Environment identifier (dev, staging, prod) | `string` | n/a | yes |
| `public_subnet_cidr` | CIDR block for the public subnet | `string` | `"10.0.1.0/24"` | no |
| `private_subnet_cidr` | CIDR block for the private subnet | `string` | `"10.0.2.0/24"` | no |
| `tags` | Resource labels | `map(string)` | `{}` | no |

## Outputs

| Name | Description | Example |
|------|-------------|---------|
| `network_id` | VPC network ID | `projects/my-project/global/networks/myapp-prod-vpc` |
| `network_name` | VPC network name | `myapp-prod-vpc` |
| `public_subnet_id` | Public subnet ID | `projects/my-project/regions/us-central1/subnetworks/myapp-prod-public-subnet` |
| `private_subnet_id` | Private subnet ID | `projects/my-project/regions/us-central1/subnetworks/myapp-prod-private-subnet` |
| `router_name` | Cloud Router name | `myapp-prod-router` |
| `nat_name` | Cloud NAT name | `myapp-prod-nat` |

## Architecture

```
+---------------------------------------------------------------+
|                VPC (myapp-prod-vpc)                            |
|                                                               |
|  +---------------------------+  +---------------------------+ |
|  |  Public Subnet            |  |  Private Subnet           | |
|  |  (10.0.1.0/24)           |  |  (10.0.2.0/24)           | |
|  |                           |  |                           | |
|  |  +---------------------+  |  |  +---------------------+ | |
|  |  | Cloud Router        |  |  |  | Cloud Functions     | | |
|  |  | + Cloud NAT         |  |  |  | Cloud Run           | | |
|  |  | (outbound internet) |<-+--+--| Memorystore Redis   | | |
|  |  +---------------------+  |  |  +---------------------+ | |
|  +---------------------------+  +---------------------------+ |
|                                                               |
|  Firewall: allow internal traffic between subnets             |
+---------------------------------------------------------------+
```

## Features

### VPC Configuration

- **Custom Mode**: No auto-created subnets. You control the IP ranges
- **Naming Convention**: `{product_alias}-{env_alias}-vpc`
- **No Default Routes**: Only routes you explicitly create

### Private Google Access

The private subnet has `private_ip_google_access = true`. This lets resources in the private subnet reach Google APIs (Firestore, Cloud Storage, etc.) without a public IP.

### Cloud NAT

- Deployed via Cloud Router in the same region
- Uses `AUTO_ONLY` IP allocation (no manual Elastic IP)
- Only NATs traffic from the private subnet
- Gives private resources outbound internet access

### Firewall Rules

- Allows TCP, UDP, and ICMP between the public and private subnets
- All external inbound traffic is blocked by default (GCP's implied deny)

## GCP vs AWS Comparison

| GCP | AWS |
|-----|-----|
| `google_compute_network` | `aws_vpc` |
| `google_compute_subnetwork` | `aws_subnet` |
| `google_compute_router` + `google_compute_router_nat` | `aws_nat_gateway` + `aws_eip` |
| Not needed (implied) | `aws_internet_gateway` |
| `google_compute_firewall` | `aws_security_group` |
| Not needed | `aws_route_table` + `aws_route` |

**Key difference**: GCP needs fewer resources. No Internet Gateway, no route tables, no Elastic IP for NAT.

## Cost Considerations

| Resource | Cost |
|----------|------|
| VPC, Subnets, Firewall | Free |
| Cloud NAT | ~$1/month + $0.045/GB processed |
| Cloud Router | Free (no charge) |

**Much cheaper than AWS**: AWS NAT Gateway costs ~$32/month + $0.045/GB. GCP Cloud NAT is ~$1/month base.

## Related Modules

- [Memorystore Module](../memorystore/) - Deploy Redis in private subnet
- [Artifact Registry Module](../artifact-registry/) - For Docker images
- [Firestore Module](../firestore/) - Document database

---

**Note**: This module creates a single-region VPC. For multi-region setups, create separate VPC modules and use VPC peering.
