# Agent Kernel - AWS Serverless Module

A comprehensive Terraform module for deploying serverless applications on AWS, combining Lambda functions with API Gateway to create production-ready RESTful APIs.

## 📋 Overview

This module provides a complete serverless deployment solution:

- ⚡ **AWS Lambda**: Configurable functions with multiple deployment options
- 🌐 **API Gateway**: REST API with Three-Level Resource Creation and Routing
- 🔄 **Flexible Deployment**: Support for ZIP packages, S3 storage, and container images
- 🔒 **Security**: Code signing, IAM roles, and CloudWatch logging
- 🔒 **Custom Authorization**: Lambda-based API Gateway authorizer support
- 📦 **Queue Mode**: SQS-driven async processing with agent runner and response handler functions
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
  source = "yaalalabs/ak-serverless/aws"

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
  
    # API Gateway
  api_version    = "v1"
  api_base_path  = "api"
  agent_endpoint = "chat"
  gateway_endpoints = [
      {
         path           = "app/test",
         method         = "GET",
      },
      {
         path           = "data",
         method         = "POST",
      }
  ] 

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
  source = "yaalalabs/ak-serverless/aws"

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
  source = "yaalalabs/ak-common/aws//modules/ecr"

  region        = "us-west-2"
  product_alias = "myapp"
  env_alias     = "prod"
  module_name   = "api"
  source_path   = "${path.module}/src"
}

# Deploy Lambda with container image
module "container_api" {
  source = "yaalalabs/ak-serverless/aws"

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
  source = "yaalalabs/ak-common/aws//modules/lambda-package"

  region           = "us-west-2"
  product_alias    = "myapp"
  env_alias        = "prod"
  module_name      = "api"
  package_dir_path = "${path.module}/dist/function.zip"
  s3_bucket        = module.storage.source_storage_s3_bucket
}

# Deploy with code signing
module "secure_api" {
  source = "yaalalabs/ak-serverless/aws"

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

### With DynamoDB for Session Storage

```hcl
module "serverless_api_dynamodb" {
  source = "yaalalabs/ak-serverless/aws"

  region              = "us-west-2"
  product_alias       = "myapp"
  env_alias           = "prod"
  product_display_name = "Serverless API with DynamoDB"
  
  module_name          = "chat"
  function_name        = "handler"
  function_description = "Chat API with DynamoDB session storage"
  handler_path         = "app.lambda_handler"
  module_type          = "python"
  
  package_type = "LocalZip"
  package_path = "${path.module}/dist/function.zip"
  
  # Enable DynamoDB for session storage
  create_dynamodb_memory_table = true
  
  timeout     = 30
  memory_size = 512
  
  environment_variables = {
    ENVIRONMENT = "production"
    # DynamoDB table name automatically injected as AK_SESSION__DYNAMODB__TABLE_NAME
  }
  
  api_version    = "v1"
  agent_endpoint = "chat"
}
```

### With Custom Authorizer

```hcl
module "serverless_api_auth" {
  source = "yaalalabs/ak-serverless/aws"

  region              = "us-west-2"
  product_alias       = "myapp"
  env_alias           = "prod"
  product_display_name = "Serverless API with Authorizer"
  
  module_name          = "api"
  function_name        = "handler"
  function_description = "Main API handler"
  handler_path         = "app.lambda_handler"
  module_type          = "python"
  
  package_type = "LocalZip"
  package_path = "${path.module}/dist/function.zip"
  
  # Authorizer configuration
  authorizer = {
    description           = "API Gateway Lambda Authorizer"
    function_name         = "api-authorizer"
    handler_path          = "auth.handler"
    package_path          = "${path.module}/dist/auth.zip"
    package_type          = "LocalZip"
    module_name           = "auth"
    result_ttl_in_seconds = 300
    environment_variables = {
      JWT_SECRET = "your-secret-key"
      API_URL    = "https://api.example.com"
    }
  }
  
  timeout     = 30
  memory_size = 512
  
  api_version    = "v1"
  agent_endpoint = "chat"
  
  environment_variables = {
    ENVIRONMENT = "production"
    LOG_LEVEL   = "info"
  }
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
| `cloudwatch_logs_retention_in_days` | CloudWatch log retention period in days for the request handler Lambda | `number` | `90` | no |
| `queue_mode` | Enable SQS-driven processing with agent runner and response handler Lambdas | `bool` | `false` | no |
| `execution_mode` | Execution mode for the deployment: `rest_sync` or `rest_async` | `string` | `null` | no |
| `event_source_mapping` | Event source mapping configuration for triggers | `any` | `[]` | no |
| `environment_variables` | Environment variables for Lambda function | `map(string)` | `{}` | no |
| `timeout` | Lambda function timeout in seconds (max 900) | `number` | `45` | no |
| `memory_size` | Lambda function memory size in MB (128-10240) | `number` | `128` | no |
| `function_name` | Lambda function name suffix | `string` | n/a | yes |
| `function_description` | Lambda function description | `string` | n/a | yes |
| `handler_path` | Handler path (e.g., `index.handler` or `app.main`) | `string` | n/a | yes |
| `image_uri` | Container image URI (required for Image package type) | `string` | `null` | no |
| `package_type` | Deployment type: `LocalZip`, `S3Zip`, or `Image` | `string` | `"LocalZip"` | no |
| `layers` | List of Lambda layer ARNs to attach | `list(string)` | `[]` | no |
| `api_version` | API version for endpoint path (e.g., `v1`, `v2`) | `string` | `"v1"` | no |
| `agent_endpoint` | API endpoint name (e.g., `chat`, `process`) | `string` | `"chat"` | no |
| `api_base_path` | Base path segment for the API | `string` | `"api"` | no |
| `gateway_endpoints` | List of REST API Gateway endpoints to expose; path values are validated and limited to three resource levels (for example, `app/test/func` or `app/check`) | `list(object)` | `[]` | no |
| `create_redis_cluster` | Create a Redis cluster for Agent session memory | `bool` | `false` | no |
| `create_dynamodb_memory_table` | Enable DynamoDB table for session storage | `bool` | `false` | no |
| `create_redis_response_store` | Create or reuse Redis for response storage | `bool` | `false` | no |
| `create_dynamodb_response_store` | Create a DynamoDB table for response storage | `bool` | `false` | no |
| `create_dynamodb_multimodal_memory_table` | Create a DynamoDB table for multimodal memory | `bool` | `false` | no |
| `authorizer` | Authorizer configuration object containing function settings (see table below) | `object` | `null` | no |
| `tags` | Additional tags for resources | `map(string)` | `{}` | no |

### Authorizer Object Structure

| Field | Description | Type | Default | Required |
|-------|-------------|------|---------|----------|
| `description` | Authorizer function description | `string` | `"API Gateway Lambda Authorizer"` | no |
| `function_name` | Authorizer Lambda function name | `string` | n/a | yes |
| `handler_path` | Authorizer Lambda handler path | `string` | n/a | yes |
| `package_path` | Authorizer package path | `string` | n/a | yes |
| `package_type` | Deployment type (`LocalZip`, `S3Zip`, or `Image`) | `string` | n/a | yes |
| `module_name` | Authorizer module name | `string` | n/a | yes |
| `result_ttl_in_seconds` | Cache TTL for authorization results | `number` | `150` | no |
| `environment_variables` | Environment variables for authorizer | `map(string)` | `{}` | no |

### Response Handler Object Structure

| Field | Description | Type | Default | Required |
|-------|-------------|------|---------|----------|
| `function_name` | Response handler Lambda function name | `string` | `"response-handler"` | no |
| `function_description` | Response handler Lambda description | `string` | `"Response handler Lambda for processing SQS messages and storing responses"` | no |
| `timeout` | Response handler Lambda timeout in seconds | `number` | `45` | no |
| `memory_size` | Response handler Lambda memory size in MB | `number` | `256` | no |
| `handler_path` | Response handler Lambda handler path | `string` | `"response_handler.handler"` | no |
| `package_path` | Response handler deployment package path | `string` | `null` | no |
| `layers` | List of Lambda layer ARNs to attach | `list(string)` | `[]` | no |
| `cloudwatch_logs_retention_in_days` | CloudWatch log retention period in days | `number` | `90` | no |
| `environment_variables` | Environment variables for the response handler | `map(string)` | `{}` | no |

### Agent Runner Object Structure

| Field | Description | Type | Default | Required |
|-------|-------------|------|---------|----------|
| `function_name` | Agent runner Lambda function name | `string` | `"agent-runner"` | no |
| `function_description` | Agent runner Lambda description | `string` | `"Agent runner Lambda for processing input queue messages"` | no |
| `timeout` | Agent runner Lambda timeout in seconds | `number` | `45` | no |
| `memory_size` | Agent runner Lambda memory size in MB | `number` | `512` | no |
| `handler_path` | Agent runner Lambda handler path | `string` | `"agent_runner.handler"` | no |
| `module_name` | Agent runner artifact module name; defaults to the root module name with `-agent-runner` appended when omitted | `string` | `null` | no |
| `package_path` | Agent runner deployment package path | `string` | `null` | no |
| `package_type` | Agent runner deployment type (`LocalZip`, `S3Zip`, or `Image`) | `string` | `"LocalZip"` | no |
| `layers` | List of Lambda layer ARNs to attach | `list(string)` | `[]` | no |
| `cloudwatch_logs_retention_in_days` | CloudWatch log retention period in days | `number` | `90` | no |
| `environment_variables` | Environment variables for the agent runner | `map(string)` | `{}` | no |

### Queue Configuration

The root `queue_config` object drives the SQS queues created for queue mode. All fields are optional and the defaults below match the module behavior.

| Field | Description | Type | Default | Required |
|-------|-------------|------|---------|----------|
| `input_queue_name` | Name suffix for the input queue | `string` | `"input-queue"` | no |
| `output_queue_name` | Name suffix for the output queue | `string` | `"output-queue"` | no |
| `input_queue_visibility_timeout` | Visibility timeout for the input queue | `number` | `60` | no |
| `input_queue_max_receive_count` | Maximum receive count before the input queue message is sent to the DLQ | `number` | `3` | no |
| `input_queue_message_retention_seconds` | Message retention period for the input queue | `number` | `300` | no |
| `input_queue_max_message_size` | Maximum message size for the input queue in bytes | `number` | `262144` | no |
| `input_queue_receive_wait_time_seconds` | Long-polling wait time for the input queue | `number` | `0` | no |
| `input_queue_delay_seconds` | Delivery delay for the input queue | `number` | `0` | no |
| `input_queue_create_dlq` | Create a dead-letter queue for the input queue | `bool` | `false` | no |
| `input_queue_dlq_message_retention_seconds` | Message retention period for the input DLQ | `number` | `300` | no |
| `output_queue_visibility_timeout` | Visibility timeout for the output queue | `number` | `60` | no |
| `output_queue_max_receive_count` | Maximum receive count before the output queue message is sent to the DLQ | `number` | `3` | no |
| `output_queue_message_retention_seconds` | Message retention period for the output queue | `number` | `300` | no |
| `output_queue_max_message_size` | Maximum message size for the output queue in bytes | `number` | `262144` | no |
| `output_queue_receive_wait_time_seconds` | Long-polling wait time for the output queue | `number` | `0` | no |
| `output_queue_delay_seconds` | Delivery delay for the output queue | `number` | `0` | no |
| `output_queue_create_dlq` | Create a dead-letter queue for the output queue | `bool` | `false` | no |
| `output_queue_dlq_message_retention_seconds` | Message retention period for the output DLQ | `number` | `300` | no |
| `fifo_queue` | Create FIFO queues instead of standard queues | `bool` | `true` | no |
| `sqs_managed_sse_enabled` | Use SQS-managed server-side encryption | `bool` | `true` | no |
| `kms_master_key_id` | Customer-managed KMS key ARN or ID for SQS encryption when managed SSE is disabled | `string` | `null` | no |
| `kms_data_key_reuse_period_seconds` | Data key reuse period for customer-managed KMS encryption when managed SSE is disabled | `number` | `null` | no |
| `content_based_deduplication` | Enable content-based deduplication for FIFO queues | `bool` | `false` | no |
| `fifo_throughput_limit` | FIFO throughput limit (`perMessageGroupId` or `perQueue`) | `string` | `"perMessageGroupId"` | no |
| `deduplication_scope` | FIFO deduplication scope (`messageGroup` or `queue`) | `string` | `"messageGroup"` | no |
| `enable_producer_access` | Enable producer access policies for the queues | `bool` | `true` | no |
| `producer_arns` | ARNs allowed to send messages to the queues | `list(string)` | `[]` | no |
| `enable_consumer_access` | Enable consumer access policies for the queues | `bool` | `true` | no |
| `consumer_role_arns` | ARNs allowed to consume messages from the queues | `list(string)` | `[]` | no |
| `batch_size` | Lambda batch size for queue event source mappings | `number` | `10` | no |
| `maximum_batching_window_in_seconds` | Maximum batching window for Lambda event source mappings | `number` | `0` | no |

**Note**: When `queue_mode = true`, the response handler and agent runner package paths must be provided. The queue configuration defaults can be used as-is, or you can override only the queue names and sizing values you need.

## 📤 Outputs

| Name | Description |
|------|-------------|
| `lambda_function_arn` | ARN of the request-handler Lambda function |
| `lambda_function_name` | Name of the request-handler Lambda function |
| `lambda_function_invoke_arn` | Invoke ARN for API Gateway integration |
| `lambda_role_arn` | ARN of the request-handler Lambda execution role |
| `authorizer_status` | Status message indicating whether the authorizer Lambda will be created |
| `agent_invoke_url` | Full invoke URL for the agent endpoint |
| `api_gateway_id` | API Gateway REST API ID |
| `api_gateway_stage_name` | API Gateway stage name |
| `api_gateway_execution_arn` | Execution ARN of the API Gateway REST API |
| `api_gateway_cloudwatch_log_group_arn` | ARN of the CloudWatch log group for API Gateway |
| `api_gateway_cloudwatch_log_group_name` | Name of the CloudWatch log group for API Gateway |
| `response_handler_lambda_function_arn` | ARN of the response handler Lambda function when `queue_mode = true` |
| `response_handler_lambda_function_name` | Name of the response handler Lambda function when `queue_mode = true` |
| `response_handler_lambda_function_invoke_arn` | Invoke ARN of the response handler Lambda function when `queue_mode = true` |
| `response_handler_lambda_role_arn` | ARN of the response handler Lambda execution role when `queue_mode = true` |
| `agent_runner_lambda_function_arn` | ARN of the agent runner Lambda function when `queue_mode = true` |
| `agent_runner_lambda_function_name` | Name of the agent runner Lambda function when `queue_mode = true` |
| `agent_runner_lambda_function_invoke_arn` | Invoke ARN of the agent runner Lambda function when `queue_mode = true` |
| `agent_runner_lambda_role_arn` | ARN of the agent runner Lambda execution role when `queue_mode = true` |
| `input_queue_arn` | ARN of the input SQS queue when `queue_mode = true` |
| `input_queue_url` | URL of the input SQS queue when `queue_mode = true` |
| `input_queue_name` | Name of the input SQS queue when `queue_mode = true` |
| `output_queue_arn` | ARN of the output SQS queue when `queue_mode = true` |
| `output_queue_url` | URL of the output SQS queue when `queue_mode = true` |
| `output_queue_name` | Name of the output SQS queue when `queue_mode = true` |

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
- `gateway_endpoints` path values are validated and the module creates up to three resource levels per endpoint
- CORS support configurable
- Custom domain support compatible
- **Custom Authorizer**: Lambda-based request authorization with configurable TTL

### 📦 Queue Mode Architecture

When `queue_mode = true`, the module adds an asynchronous queue-driven path alongside the API Gateway entrypoint.

**What gets created**:
- Input and output SQS queues
- An agent runner Lambda that consumes the input queue
- A response handler Lambda that consumes the output queue
- Event source mappings for both queue consumers

**Execution modes**:
- `rest_sync`: synchronous REST requests
- `rest_async`: chat path will have a POST and GET method, POST method would be to send the request, GET method is to get the response for that request (by `request_id`) via polling 

**Operational rules**:
- Input queue visibility timeout must be greater than or equal to the agent runner timeout
- Output queue visibility timeout must be greater than or equal to the response handler timeout
- FIFO queues are enabled by default, with explicit deduplication controls available when needed

### 💾 Multi-Storage Support

The module supports the current Agent Kernel storage wiring for both session state and response persistence.

**Available storage options**:
- Redis session memory via `create_redis_cluster`
- Redis response storage via `create_redis_response_store`
- Redis multimodal memory via `create_redis_cluster` and environmental variables *(more details in Agent Kernel Docs in Multimodal section)*
- DynamoDB session memory via `create_dynamodb_memory_table`
- DynamoDB multimodal memory via `create_dynamodb_multimodal_memory_table`
- DynamoDB response storage via `create_dynamodb_response_store`

**Behavior notes**:
- Redis and DynamoDB response storage are mutually exclusive
- DynamoDB-backed response storage uses a session-aware table layout with a `session_id` secondary index
- Multimodal memory is stored separately from the core session store

### 🔒 Security Features

- **IAM Roles**: Automatic Lambda execution role creation
- **CloudWatch Logs**: 90-day retention by default
- **Code Signing**: Optional for production deployments
- **VPC Support**: Compatible with VPC-based Lambda
- **Encryption**: KMS encryption support for environment variables
- **Custom Authorization**: Lambda-based API Gateway authorizer for request authentication and authorization

### 🏷️ Naming Conventions

Resources follow consistent naming:
- Lambda Function: `{product_alias}-{env_alias}-{module_name}-{function_name}`
- Authorizer Lambda: `{product_alias}-{env_alias}-{authorizer.module_name}-{authorizer.function_name}`
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
  source = "yaalalabs/ak-serverless/aws"
  
  module_name    = "chat"
  function_name  = "handler"
  agent_endpoint = "chat"
  api_version    = "v1"
  # ... other config
}

# Process endpoint
module "process_api" {
  source = "yaalalabs/ak-serverless/aws"
  
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
  source = "yaalalabs/ak-serverless/aws"
  
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
  source      = "yaalalabs/ak-serverless/aws"
  module_name = "api"
  api_version = "v1"
  # ... config
}

# V2 API (backward compatible)
module "api_v2" {
  source      = "yaalalabs/ak-serverless/aws"
  module_name = "api"
  api_version = "v2"
  # ... config with new features
}
```

### Async Processing with Queue Mode

```hcl
module "async_api" {
  source = "yaalalabs/ak-serverless/aws"

  region               = "us-west-2"
  product_alias        = "myapp"
  env_alias            = "prod"
  product_display_name  = "Async API"

  module_name          = "chat"
  function_name        = "handler"
  function_description = "Main API handler"
  handler_path         = "app.lambda_handler"
  module_type          = "python"

  package_type = "LocalZip"
  package_path = "${path.module}/dist/function.zip"

  queue_mode = true
  execution_mode = "rest_async"
  ...

  response_handler = {
    package_path = "${path.module}/dist/response-handler.zip"
    ...
  }

  agent_runner = {
    package_path = "${path.module}/dist/agent-runner.zip"
    ...
  }

  queue_config = {
    input_queue_name  = "chat-input"
    output_queue_name = "chat-output"
    ...
  }

  create_redis_response_store = true
  create_dynamodb_multimodal_memory_table = true

  api_version    = "v1"
  agent_endpoint = "chat"

  environment_variables = {
    ENVIRONMENT = "production"
  }
  ...
}
```

Swap `create_redis_response_store = true` for `create_dynamodb_response_store = true` if you want DynamoDB-backed response storage instead of Redis.

## 🔐 Custom Authorizer Configuration

The module supports a Lambda-based API Gateway authorizer for custom authentication and authorization logic.

### Authorizer Setup

The authorizer is configured using a single `authorizer` object that contains all the necessary settings:

```hcl
authorizer = {
  description           = "API Gateway Lambda Authorizer"  # Optional, defaults to this value
  function_name         = "api-authorizer"                 # Required
  handler_path          = "auth.handler"                   # Required
  package_path          = "./dist/auth.zip"                # Required
  package_type          = "LocalZip"                       # Required
  module_name           = "auth"                           # Required
  result_ttl_in_seconds = 0                                # Optional, defaults to 150
  environment_variables = {                                # Optional, defaults to {}
    JWT_SECRET = "your-secret-key"
    API_URL    = "https://api.example.com"
  }
}
```

**Required Fields**:
- `function_name` - Name for the authorizer Lambda function
- `handler_path` - Path to the authorizer Lambda handler (e.g., `auth.handler`)
- `package_type` - Deployment type (`Image`, `LocalZip`, or `S3Zip`)
- `package_path` - Path to authorizer deployment package
- `module_name` - Authorizer module name

**Optional Fields**:
- `description` - Description of the authorizer function (defaults to "API Gateway Lambda Authorizer")
- `result_ttl_in_seconds` - Cache TTL for authorization results (default: 150)
- `environment_variables` - Environment variables for authorizer

**Note**: The authorizer infrastructure will only be created if the `authorizer` object is provided and all required fields are present. If any required field is missing, no authorizer will be created and your endpoints will be publicly accessible.

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

## License

Unless otherwise specified, all content, including all source code files and documentation files in this repository are:

Copyright (c) 2025-2026 Yaala Labs.

Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with the License. You may obtain a copy of the License at

http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the License for the specific language governing permissions and limitations under the License.