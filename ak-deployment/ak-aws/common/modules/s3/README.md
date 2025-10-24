# S3 Module

A Terraform module for creating secure, compliant S3 buckets optimized for Lambda function deployment packages, application data storage, and secure file management.

## 📋 Overview

This module implements AWS S3 best practices out-of-the-box:

- 🔒 **Security First**: Blocks public access, enforces SSL/TLS, and implements bucket policies
- 🔐 **Encryption**: Configurable KMS encryption for production environments
- 📦 **Versioning**: Automatic versioning for production deployments
- 🏷️ **Tagging**: Standardized tagging for cost allocation and compliance
- 🔄 **Lambda Integration**: Pre-configured policies for Lambda service access
- 📝 **Compliance Ready**: Meets common security and compliance requirements

Perfect for storing Lambda deployment packages, application data, logs, and any sensitive content requiring secure storage.

## 📋 Requirements

| Name | Version |
|------|---------|
| Terraform | >= 1.9.5 |
| AWS Provider | >= 6.11.0 |

## 🚀 Usage

### Basic Example

```hcl
module "app_storage" {
  source = "yaalalabs/ak-common/aws//modules/s3"

  region               = "us-west-2"
  product_alias        = "myapp"
  env_alias            = "dev"
  product_display_name = "My Application"
  is_production        = false
}
```

### Production Configuration with KMS Encryption

```hcl
# Create KMS key for encryption
resource "aws_kms_key" "s3_encryption" {
  description             = "KMS key for S3 bucket encryption"
  deletion_window_in_days = 10
  enable_key_rotation     = true
}

module "prod_storage" {
  source = "yaalalabs/ak-common/aws//modules/s3"

  region               = "us-west-2"
  product_alias        = "myapp"
  env_alias            = "prod"
  product_display_name = "My Application"
  is_production        = true
  s3_kms_key_id        = aws_kms_key.s3_encryption.id
  
  s3_bucket_tags = {
    Compliance   = "HIPAA"
    DataClass    = "Sensitive"
    CostCenter   = "Engineering"
  }
}
```

### Multi-Purpose Storage

```hcl
# Lambda deployment packages
module "lambda_packages" {
  source = "yaalalabs/ak-common/aws//modules/s3"

  region               = "us-west-2"
  product_alias        = "myapp"
  env_alias            = "prod"
  product_display_name = "Lambda Packages"
  is_production        = true
  
  s3_bucket_tags = {
    Purpose = "lambda-deployments"
  }
}

# Application data storage
module "app_data" {
  source = "yaalalabs/ak-common/aws//modules/s3"

  region               = "us-west-2"
  product_alias        = "myapp"
  env_alias            = "prod"
  product_display_name = "Application Data"
  is_production        = true
  
  s3_bucket_tags = {
    Purpose = "application-data"
  }
}
```


## 📥 Inputs

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|:--------:|
| `region` | AWS region for S3 bucket deployment | `string` | n/a | yes |
| `product_alias` | Short identifier for the product (e.g., "myapp") | `string` | n/a | yes |
| `env_alias` | Environment identifier (e.g., "dev", "staging", "prod") | `string` | n/a | yes |
| `product_display_name` | Human-readable product name for tagging | `string` | n/a | yes |
| `is_production` | Enable production features (versioning, encryption) | `bool` | n/a | yes |
| `s3_bucket_tags` | Additional custom tags for the bucket | `map(string)` | `{}` | no |
| `s3_kms_key_id` | KMS key ID for server-side encryption (prod only) | `string` | `null` | no |

## 📤 Outputs

| Name | Description | Example |
|------|-------------|---------|
| `source_storage_s3_bucket` | The ID/name of the created S3 bucket | `myapp-prod-sources-123456789012` |
| `bucket_arn` | ARN of the S3 bucket | `arn:aws:s3:::myapp-prod-sources-123456789012` |
| `bucket_regional_domain_name` | Regional domain name of the bucket | `myapp-prod-sources-123456789012.s3.us-west-2.amazonaws.com` |

## ✨ Features

### 🔒 Security Configuration

- **Public Access Blocking**: All four public access block settings enabled
- **SSL/TLS Enforcement**: Bucket policy denies non-HTTPS requests
- **IAM Integration**: Supports Lambda service access for deployment packages
- **Encryption**: KMS encryption available for production environments
- **Secure by Default**: No public access, encrypted in transit

### 📦 Bucket Configuration

- **Naming Convention**: `{product_alias}-{env_alias}-sources-{account_id}`
- **Versioning**: Automatically enabled for production (`is_production = true`)
- **Force Destroy**: Enabled to allow Terraform to clean up buckets
- **Tags**: Automatic tagging with environment, product, and backup config

### 🔐 Access Control

The module configures two primary bucket policies:

1. **SSL/TLS Enforcement**
   ```json
   {
     "Effect": "Deny",
     "Principal": "*",
     "Action": "s3:*",
     "Resource": "arn:aws:s3:::bucket-name/*",
     "Condition": {
       "Bool": {
         "aws:SecureTransport": "false"
       }
     }
   }
   ```

2. **Lambda Service Access**
   - Allows Lambda to read objects (`s3:GetObject`)
   - Scoped to Lambda service principal

## 🎯 Best Practices

### Development Environment

```hcl
module "dev_storage" {
  source = "yaalalabs/ak-common/aws//modules/s3"

  region               = "us-west-2"
  product_alias        = "myapp"
  env_alias            = "dev"
  product_display_name = "My App Development"
  is_production        = false  # No versioning/encryption overhead
}
```

### Production Environment

```hcl
module "prod_storage" {
  source = "yaalalabs/ak-common/aws//modules/s3"

  region               = "us-west-2"
  product_alias        = "myapp"
  env_alias            = "prod"
  product_display_name = "My App Production"
  is_production        = true         # Enables versioning
  s3_kms_key_id        = aws_kms_key.prod.id  # KMS encryption
  
  s3_bucket_tags = {
    Compliance     = "SOC2"
    DataClass      = "Confidential"
    BackupRequired = "true"
  }
}
```

## 📊 Storage Cost Optimization

1. **Use S3 Lifecycle Policies**: Transition old versions to cheaper storage classes
2. **Enable Intelligent-Tiering**: For variable access patterns
3. **Monitor Metrics**: Use S3 Storage Lens for optimization insights
4. **Clean Up**: Remove unused objects and incomplete multipart uploads

## 🔍 Common Use Cases

### Lambda Deployment Packages

```hcl
module "lambda_storage" {
  source = "yaalalabs/ak-common/aws//modules/s3"

  region               = "us-west-2"
  product_alias        = "myapp"
  env_alias            = "prod"
  product_display_name = "Lambda Packages"
  is_production        = true
}

# Upload Lambda package
resource "aws_s3_object" "lambda_package" {
  bucket = module.lambda_storage.source_storage_s3_bucket
  key    = "functions/api/v1.0.0/function.zip"
  source = "dist/function.zip"
  etag   = filemd5("dist/function.zip")
}
```

### Application Data Storage

```hcl
module "data_storage" {
  source = "yaalalabs/ak-common/aws//modules/s3"

  region               = "us-west-2"
  product_alias        = "myapp"
  env_alias            = "prod"
  product_display_name = "Application Data"
  is_production        = true
  s3_kms_key_id        = aws_kms_key.data_key.id
  
  s3_bucket_tags = {
    Purpose       = "user-uploads"
    RetentionDays = "90"
  }
}
```

## 🔍 Troubleshooting

### Access Denied Errors

**Issue**: Cannot upload or read objects from bucket
```
Error: Access Denied
```

**Solution**: 
1. Verify IAM permissions include `s3:PutObject` and `s3:GetObject`
2. Check bucket policy allows your principal
3. Ensure SSL/TLS is being used for requests

### Versioning Not Enabled

**Issue**: Versioning is not working

**Solution**: Set `is_production = true` to enable versioning:
```hcl
module "storage" {
  # ... other config
  is_production = true
}
```

### KMS Encryption Errors

**Issue**: Encryption fails with KMS key
```
Error: Access to KMS is not allowed
```

**Solution**: Ensure the KMS key policy allows S3 service:
```hcl
resource "aws_kms_key" "s3" {
  policy = jsonencode({
    Statement = [{
      Sid    = "Enable S3 to use the key"
      Effect = "Allow"
      Principal = {
        Service = "s3.amazonaws.com"
      }
      Action = [
        "kms:Decrypt",
        "kms:GenerateDataKey"
      ]
      Resource = "*"
    }]
  })
}
```

## 🔒 Security Considerations

1. **Enable MFA Delete**: For production buckets storing critical data
2. **Use KMS Keys**: Always use KMS encryption for sensitive data
3. **Audit Access**: Enable S3 access logging and CloudTrail
4. **Limit Permissions**: Use least-privilege IAM policies
5. **Regular Reviews**: Audit bucket policies and access patterns

## 📚 Additional Resources

- [AWS S3 Security Best Practices](https://docs.aws.amazon.com/AmazonS3/latest/userguide/security-best-practices.html)
- [S3 Encryption](https://docs.aws.amazon.com/AmazonS3/latest/userguide/UsingEncryption.html)
- [S3 Versioning](https://docs.aws.amazon.com/AmazonS3/latest/userguide/Versioning.html)

## 🔗 Related Modules

- [Lambda Package Module](../lambda-package/) - For managing Lambda deployment packages
- [ECR Module](../ecr/) - For container image storage

---

**Note**: Bucket names must be globally unique across all AWS accounts. This module uses the AWS account ID in the naming pattern to ensure uniqueness.