# AWS Serverless Module

A comprehensive Terraform module for deploying serverless applications on AWS, combining Lambda functions with API Gateway to create production-ready RESTful APIs.

## 📋 Overview

This module provides a complete serverless deployment solution:

- ⚡ **AWS Lambda**: Configurable functions with multiple deployment options
- 🌐 **API Gateway**: REST API with structured endpoint routing
- 🔄 **Flexible Deployment**: Support for ZIP packages, S3 storage, and container images
- 🔒 **Security**: Code signing, IAM roles, and CloudWatch logging
- 🏷️ **Best Practices**: Automatic runtime selection and resource tagging
- 📊 **Monitoring**: CloudWatch logs with configurable retention

Perfect for microservices, API backends, event-driven architectures, and serverless web applications requiring REST endpoints.

## 📋 Requirements

| Name | Version |
|------|---------|
| Terraform | >= 1.9.5 |
| AWS Provider | >= 6.11.0 |

## 🚀 Usage

### Basic Python API

```hcl
module "python_api" {
  source = "app.terraform.io/yaalalabs/ak-aws-serverless/aws"

  region              = "us-west-2"
  product_alias       = "myapp"
  env_alias           = "prod"
  product_display_name = "My Application API"
  
  module_name          = "api"
  function_name        = "handler"
  function_description = "Main API handler"
  handler_path         = "app.lambda_handler"
  module_type          = "python"
  
  package_type         = "LocalZip"
  package_path         = "${path.module}/dist/function.zip"
  
  timeout              = 30
  memory_size          = 512
  
  environment_variables = {
    ENVIRONMENT = "production"
    LOG_LEVEL   = "info"
  }
  
  api_version    = "v1"
  agent_endpoint = "process"
  
  tags = {
    Environment = "production"
    Service     = "api"
  }
}

output "api_url" {
  value = module.python_api.agent_invoke_url
}
```

### Node.js API with Layers

```hcl
# Create layer for dependencies
resource "aws_lambda_layer_version" "dependencies" {
  layer_name          = "myapp-dependencies"
  filename            = "${path.module}/dist/layer.zip"
  compatible_runtimes = ["nodejs22.x"]
}

# Deploy Node.js function with layer
module "nodejs_api" {
  source = "app.terraform.io/yaalalabs/ak-aws-serverless/aws"

  region              = "us-west-2"
  product_alias       = "myapp"
  env_alias           = "prod"
  product_display_name = "Node.js API"
  
  module_name          = "chat"
  function_name        = "handler"
  function_description = "Chat API endpoint"
  handler_path         = "index.handler"
  module_type          = "nodejs"
  
  package_type = "LocalZip"
  package_path = "${path.module}/dist/function.zip"
  
  layers = [aws_lambda_layer_version.dependencies.arn]
  
  timeout     = 60
  memory_size = 1024
  
  environment_variables = {
    NODE_ENV = "production"
  }
  
  api_version    = "v2"
  agent_endpoint = "chat"
}
```

### Container Image Deployment

```hcl
# Use ECR module to build image
module "container_image" {
  source = "app.terraform.io/yaalalabs/ak-aws-common/aws//modules/ecr"

  region        = "us-west-2"
  product_alias = "myapp"
  env_alias     = "prod"
  module_name   = "api"
  source_path   = "${path.module}/src"
}

# Deploy Lambda with container image
module "container_api" {
  source = "app.terraform.io/yaalalabs/ak-aws-serverless/aws"

  region              = "us-west-2"
  product_alias       = "myapp"
  env_alias           = "prod"
  product_display_name = "Container API"
  
  module_name          = "api"
  function_name        = "processor"
  function_description = "Containerized API handler"
  handler_path         = "app.handler"  # Used for metadata only
  module_type          = "python"
  
  package_type = "Image"
  image_uri    = module.container_image.docker_image_uri
  
  timeout     = 120
  memory_size = 2048
  
  environment_variables = {
    WORKERS = "4"
  }
  
  api_version    = "v1"
  agent_endpoint = "process"
}
```

### S3-Based Deployment with Code Signing

```hcl
# Upload package to S3
module "lambda_package" {
  source = "app.terraform.io/yaalalabs/ak-aws-common/aws//modules/lambda-package"

  region           = "us-west-2"
  product_alias    = "myapp"
  env_alias        = "prod"
  module_name      = "api"
  package_dir_path = "${path.module}/dist/function.zip"
  s3_bucket        = module.storage.source_storage_s3_bucket
}

# Deploy with code signing
module "secure_api" {
  source = "app.terraform.io/yaalalabs/ak-aws-serverless/aws"

  region              = "us-west-2"
  product_alias       = "myapp"
  env_alias           = "prod"
  product_display_name = "Secure API"
  
  module_name          = "api"
  function_name        = "handler"
  function_description = "Production API with code signing"
  handler_path         = "app.handler"
  module_type          = "python"
  
  package_type  = "S3Zip"
  package_path  = "s3://${module.lambda_package.s3_bucket}/${module.lambda_package.s3_key}"
  is_production = true  # Enables code signing
  
  timeout     = 30
  memory_size = 256
  
  api_version    = "v1"
  agent_endpoint = "api"
}
```


## 📥 Inputs

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|:--------:|
| `region` | AWS region for deployment | `string` | n/a | yes |
| `product_alias` | Short identifier for the product (e.g., "myapp") | `string` | n/a | yes |
| `env_alias` | Environment identifier (e.g., "dev", "staging", "prod") | `string` | n/a | yes |
| `product_display_name` | Human-readable product name for tagging | `string` | `"An Agent Kernel deployment"` | no |
| `module_type` | Runtime type: `python` or `nodejs` | `string` | `"python"` | no |
| `module_name` | Module name for resource identification | `string` | n/a | yes |
| `is_production` | Enable production features (code signing) | `bool` | `false` | no |
| `package_path` | Path to Lambda deployment package or S3 URI | `string` | n/a | yes |
| `event_source_mapping` | Event source mapping configuration for triggers | `any` | `[]` | no |
| `environment_variables` | Environment variables for Lambda function | `map(string)` | `{}` | no |
| `timeout` | Lambda function timeout in seconds (max 900) | `number` | `30` | no |
| `memory_size` | Lambda function memory size in MB (128-10240) | `number` | `128` | no |
| `function_name` | Lambda function name suffix | `string` | n/a | yes |
| `function_description` | Lambda function description | `string` | n/a | yes |
| `handler_path` | Handler path (e.g., `index.handler` or `app.main`) | `string` | n/a | yes |
| `image_uri` | Container image URI (required for Image package type) | `string` | `null` | no |
| `package_type` | Deployment type: `LocalZip`, `S3Zip`, or `Image` | `string` | `"LocalZip"` | no |
| `layers` | List of Lambda layer ARNs to attach | `list(string)` | `[]` | no |
| `api_version` | API version for endpoint path (e.g., `v1`, `v2`) | `string` | `"v1"` | no |
| `agent_endpoint` | API endpoint name (e.g., `chat`, `process`) | `string` | `"chat"` | no |
| `tags` | Additional tags for resources | `map(string)` | `{}` | no |

## 📤 Outputs

| Name | Description | Example |
|------|-------------|---------|
| `lambda_function_arn` | ARN of the Lambda function | `arn:aws:lambda:us-west-2:123456789012:function:myapp-prod-api-handler` |
| `lambda_function_name` | Name of the Lambda function | `myapp-prod-api-handler` |
| `lambda_function_invoke_arn` | Invoke ARN for API Gateway integration | `arn:aws:apigateway:us-west-2:lambda:path/2015-03-31/functions/...` |
| `agent_invoke_url` | Full HTTPS URL to invoke the API endpoint | `https://abc123.execute-api.us-west-2.amazonaws.com/agents/api/v1/chat` |
| `api_gateway_id` | API Gateway REST API ID | `abc123defg` |
| `api_gateway_stage_name` | API Gateway stage name | `agents` |

## ✨ Features

### ⚡ Lambda Configuration

**Multiple Deployment Methods**:
- **LocalZip**: Deploy from local ZIP file (< 50 MB)
- **S3Zip**: Deploy from S3 bucket with optional code signing
- **Image**: Deploy from ECR container image (up to 10 GB)

**Automatic Runtime Selection**:
- `module_type = "python"` → Python 3.12 runtime
- `module_type = "nodejs"` → Node.js 22.x runtime

**Resource Optimization**:
- Memory: 128 MB to 10,240 MB (in 1 MB increments)
- Timeout: 1 to 900 seconds (15 minutes)
- CPU scales automatically with memory

### 🌐 API Gateway Integration

**Structured Endpoint Path**:
```
https://{api-id}.execute-api.{region}.amazonaws.com/{stage}/api/{version}/{endpoint}
```

**Example**: `/api/v1/chat`

**Features**:
- REST API Gateway with Lambda proxy integration
- Stage name: `agents` (production-ready)
- CORS support configurable
- Custom domain support compatible

### 🔒 Security Features

- **IAM Roles**: Automatic Lambda execution role creation
- **CloudWatch Logs**: 90-day retention by default
- **Code Signing**: Optional for production deployments
- **VPC Support**: Compatible with VPC-based Lambda
- **Encryption**: KMS encryption support for environment variables

### 🏷️ Naming Conventions

Resources follow consistent naming:
- Lambda Function: `{product_alias}-{env_alias}-{module_name}-{function_name}`
- API Gateway: `{product_alias}-{env_alias}-{module_name}-api`
- CloudWatch Logs: `/aws/lambda/{function_name}`

## 🎯 Best Practices

### 1. Right-Size Your Functions

```hcl
# Light API calls
memory_size = 256
timeout     = 10

# Data processing
memory_size = 1024
timeout     = 60

# Heavy compute
memory_size = 3008
timeout     = 300
```

### 2. Use Layers for Dependencies

```hcl
# Separate dependencies into layers
# Benefits: Faster deployments, shared libraries, smaller function packages

module "api_function" {
  # ... other config
  package_path = "function-only.zip"  # Small, code only
  layers = [
    aws_lambda_layer_version.dependencies.arn,
    aws_lambda_layer_version.utilities.arn
  ]
}
```

### 3. Environment-Specific Configuration

```hcl
locals {
  config = {
    dev = {
      memory_size = 256
      timeout     = 30
      is_production = false
    }
    prod = {
      memory_size = 1024
      timeout     = 60
      is_production = true
    }
  }
  env_config = local.config[var.env_alias]
}

module "api" {
  # ... other config
  memory_size   = local.env_config.memory_size
  timeout       = local.env_config.timeout
  is_production = local.env_config.is_production
}
```

### 4. Production Checklist

✅ Enable code signing (`is_production = true`)  
✅ Use appropriate memory and timeout  
✅ Configure CloudWatch alarms  
✅ Enable X-Ray tracing  
✅ Set up proper IAM policies  
✅ Use environment variables for config  
✅ Implement error handling  
✅ Test with realistic load  

## 📊 Performance Tuning

### Memory and Cost Optimization

| Memory (MB) | vCPU | Cost/ms (US East) | Use Case |
|-------------|------|-------------------|----------|
| 128 | 0.08 | $0.0000000021 | Simple APIs |
| 512 | 0.33 | $0.0000000083 | Standard APIs |
| 1024 | 0.58 | $0.0000000167 | Data processing |
| 3008 | 1.75 | $0.0000000500 | CPU-intensive |
| 10240 | 6.00 | $0.0000001700 | Heavy compute |

**Tip**: More memory = more CPU = faster execution = potentially lower cost!

### Cold Start Optimization

1. **Minimize Package Size**: Use layers, exclude dev dependencies
2. **Provisioned Concurrency**: For latency-sensitive APIs (additional cost)
3. **Keep Warm**: CloudWatch Events ping for critical functions
4. **Language Choice**: Node.js/Python typically faster cold starts than Java/.NET

## 🔧 Common Patterns

### Multi-Endpoint API

```hcl
# Chat endpoint
module "chat_api" {
  source = "app.terraform.io/yaalalabs/ak-aws-serverless/aws"
  
  module_name    = "chat"
  function_name  = "handler"
  agent_endpoint = "chat"
  api_version    = "v1"
  # ... other config
}

# Process endpoint
module "process_api" {
  source = "app.terraform.io/yaalalabs/ak-aws-serverless/aws"
  
  module_name    = "process"
  function_name  = "handler"
  agent_endpoint = "process"
  api_version    = "v1"
  # ... other config
}

# Results in:
# /api/v1/chat
# /api/v1/process
```

### Event-Driven Architecture

```hcl
module "event_processor" {
  source = "app.terraform.io/yaalalabs/ak-aws-serverless/aws"
  
  # ... basic config
  
  event_source_mapping = [
    {
      event_source_arn = aws_sqs_queue.tasks.arn
      batch_size       = 10
    }
  ]
}
```

### Versioned APIs

```hcl
# V1 API
module "api_v1" {
  source      = "app.terraform.io/yaalalabs/ak-aws-serverless/aws"
  module_name = "api"
  api_version = "v1"
  # ... config
}

# V2 API (backward compatible)
module "api_v2" {
  source      = "app.terraform.io/yaalalabs/ak-aws-serverless/aws"
  module_name = "api"
  api_version = "v2"
  # ... config with new features
}
```

## 🔍 Troubleshooting

### Lambda Function Fails to Deploy

**Issue**: Package too large
```
Error: Unzipped size must be smaller than...
```

**Solutions**:
1. Use layers for dependencies
2. Remove unnecessary files (tests, docs)
3. Use container images for > 250 MB
4. Optimize dependencies (use `--production` flag)

### API Gateway 502 Errors

**Issue**: Lambda timeout or error
```
{"message": "Internal server error"}
```

**Solutions**:
1. Check CloudWatch Logs:
   ```bash
   aws logs tail /aws/lambda/function-name --follow
   ```
2. Increase timeout if processing takes longer
3. Check Lambda function returns proper response format
4. Verify IAM permissions

### Cold Start Latency

**Issue**: First request slow

**Solutions**:
```hcl
# Option 1: Provisioned Concurrency
resource "aws_lambda_provisioned_concurrency_config" "api" {
  function_name                     = module.api.lambda_function_name
  provisioned_concurrent_executions = 2
  qualifier                         = aws_lambda_alias.live.name
}

# Option 2: Keep-warm ping
resource "aws_cloudwatch_event_rule" "keep_warm" {
  name                = "keep-lambda-warm"
  schedule_expression = "rate(5 minutes)"
}

resource "aws_cloudwatch_event_target" "lambda" {
  rule      = aws_cloudwatch_event_rule.keep_warm.name
  target_id = "KeepWarm"
  arn       = module.api.lambda_function_arn
  input     = jsonencode({ "warmer": true })
}
```

### Environment Variables Not Working

**Issue**: Function can't read environment variables

**Solution**: Verify configuration:
```hcl
module "api" {
  # ... other config
  environment_variables = {
    DB_HOST = "database.example.com"
    API_KEY = var.api_key  # From secrets manager
  }
}
```

Access in code:
```python
import os
db_host = os.environ.get('DB_HOST')
```

## 💰 Cost Optimization

### Estimate Monthly Costs

```python
# Example: 1M requests/month, 512MB, 200ms avg
requests = 1_000_000
memory_mb = 512
duration_ms = 200

# Free tier: 1M requests, 400,000 GB-seconds
billable_requests = max(0, requests - 1_000_000)
gb_seconds = (requests * memory_mb / 1024 * duration_ms / 1000)
billable_gb_seconds = max(0, gb_seconds - 400_000)

cost_requests = billable_requests * 0.0000002  # $0.20 per 1M
cost_compute = billable_gb_seconds * 0.0000166667  # $0.0000166667 per GB-second

total = cost_requests + cost_compute
print(f"Estimated monthly cost: ${total:.2f}")
```

### Tips:
1. **Right-size memory**: Test different configurations
2. **Reduce timeout**: Don't set higher than needed
3. **Optimize code**: Faster execution = lower cost
4. **Use layers**: Reduce deployment package processing
5. **Cache responses**: API Gateway caching available

## 📚 Additional Resources

- [AWS Lambda Documentation](https://docs.aws.amazon.com/lambda/)
- [API Gateway Documentation](https://docs.aws.amazon.com/apigateway/)
- [Lambda Pricing Calculator](https://aws.amazon.com/lambda/pricing/)
- [Lambda Best Practices](https://docs.aws.amazon.com/lambda/latest/dg/best-practices.html)

## 🔗 Related Modules

- [Lambda Package Module](../common/modules/lambda-package/) - For managing Lambda packages in S3
- [ECR Module](../common/modules/ecr/) - For container-based deployments
- [VPC Module](../common/modules/vpc/) - For VPC-enabled Lambda functions
- [S3 Module](../common/modules/s3/) - For Lambda package storage

---

**Note**: This module automatically creates IAM roles, CloudWatch log groups, and API Gateway resources. Ensure your AWS credentials have sufficient permissions to create these resources.