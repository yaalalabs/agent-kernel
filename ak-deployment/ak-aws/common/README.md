# Agent Kernel - AWS Common Infrastructure Modules

A collection of reusable Terraform modules for building AWS infrastructure, optimized for serverless and containerized applications.

## 📦 Available Modules

This package provides the following Terraform modules:

- **[ECR](modules/ecr/)** - Amazon Elastic Container Registry setup with lifecycle policies
- **[S3](modules/s3/)** - S3 bucket configuration with best practices
- **[VPC](modules/vpc/)** - VPC with public/private subnets and NAT gateway
- **[Redis](modules/redis/)** - ElastiCache Redis cluster configuration
- **[Lambda Package](modules/lambda-package/)** - Lambda function packaging utilities

## 🚀 Quick Start

### Prerequisites

- Terraform >= 1.9.5
- AWS Provider >= 6.11.0
- Valid AWS credentials configured

### Basic Usage

Each module can be used independently by referencing it as a submodule:

```hcl
# ECR Module
module "ecr" {
  source = "yaalalabs/ak-common/aws//modules/ecr"
  
  region        = "us-west-2"
  product_alias = "myapp"
  env_alias     = "prod"
  module_name   = "api"
  source_path   = "${path.module}/src"
}

# VPC Module
module "vpc" {
  source = "yaalalabs/ak-common/aws//modules/vpc"
  
  vpc_cidr             = "10.0.0.0/16"
  public_subnet_cidrs  = ["10.0.1.0/24", "10.0.2.0/24"]
  private_subnet_cidrs = ["10.0.3.0/24", "10.0.4.0/24"]
  product_alias        = "myapp"
  env_alias            = "prod"
}

# Redis Module
module "redis" {
  source = "yaalalabs/ak-common/aws//modules/redis"
  
  product_alias = "myapp"
  env_alias     = "prod"
  vpc_id        = module.vpc.vpc_id
  subnet_ids    = module.vpc.private_subnet_ids
}

# S3 Module
module "s3" {
  source = "yaalalabs/ak-common/aws//modules/s3"
  
  product_alias = "myapp"
  env_alias     = "prod"
  bucket_name   = "my-application-data"
}

# Lambda Package Module
module "lambda_package" {
  source = "yaalalabs/ak-common/aws//modules/lambda-package"
  
  source_path   = "${path.module}/lambda"
  output_path   = "${path.module}/dist/lambda.zip"
}
```

## 📚 Module Documentation

Each module has its own comprehensive documentation:

- [ECR Module Documentation](modules/ecr/README.md)
- [S3 Module Documentation](modules/s3/README.md)
- [VPC Module Documentation](modules/vpc/README.md)
- [Redis Module Documentation](modules/redis/README.md)
- [Lambda Package Module Documentation](modules/lambda-package/README.md)


## 🔧 Requirements

| Name | Version |
|------|---------|
| Terraform | >= 1.9.5 |
| AWS Provider | >= 6.11.0 |

## 💡 Common Patterns

### Serverless Application Stack

```hcl
# Create VPC for Lambda functions
module "vpc" {
  source = "yaalalabs/ak-common/aws//modules/vpc"
  
  product_alias = var.product_alias
  env_alias     = var.env_alias
}

# Create Redis cache
module "redis" {
  source = "yaalalabs/ak-common/aws//modules/redis"
  
  product_alias = var.product_alias
  env_alias     = var.env_alias
  vpc_id        = module.vpc.vpc_id
  subnet_ids    = module.vpc.private_subnet_ids
}

# Create ECR and build container image
module "container_image" {
  source = "yaalalabs/ak-common/aws//modules/ecr"
  
  product_alias = var.product_alias
  env_alias     = var.env_alias
  module_name   = "api"
  source_path   = "${path.module}/src"
}

# Create S3 bucket for data storage
module "storage" {
  source = "yaalalabs/ak-common/aws//modules/s3"
  
  product_alias = var.product_alias
  env_alias     = var.env_alias
  bucket_name   = "application-data"
}
```

## 🤝 Contributing

Contributions are welcome! Please refer to the main repository for contribution guidelines.

## 📄 License

This project is licensed under the terms specified in the LICENSE file.

## 🔗 Related Projects

- [Agent Kernel](https://github.com/yaalalabs/agent-kernel) - The main Agent Kernel project

## 📞 Support

For issues, questions, or contributions, please refer to the main repository's issue tracker.

---

## 📝 Technical Notes

This is a registry-compatible root module that contains no resources itself. All functionality is provided through submodules located in the `modules/` directory. This structure allows for:

- **Selective consumption**: Use only the modules you need
- **Independent versioning**: Each module evolves independently
- **Registry compatibility**: Conforms to Terraform registry requirements
- **Namespace isolation**: Clean module paths via `//modules/<name>` syntax

**Important**: Always reference modules using the `//modules/<module-name>` syntax as shown in the usage examples above.
