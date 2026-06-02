# Authorizer Module

This Terraform module creates a Lambda-based API Gateway authorizer for custom authentication and authorization logic.

## Features

- **Lambda Authorizer**: Creates a Lambda function that can be used as a custom API Gateway authorizer
- **Multiple Deployment Types**: Support for LocalZip, S3Zip, and Docker image deployments
- **VPC Support**: Optional VPC deployment with security groups
- **Code Signing**: Optional code signing for production deployments
- **IAM Roles**: Automatically creates necessary IAM roles and policies
- **Flexible Configuration**: Extensive configuration options for timeouts, memory, environment variables

## Usage

```hcl
module "authorizer" {
  source = "yaalalabs/ak-common/aws//modules/authorizer"
  version = "0.2.11"
  
  region        = "us-west-2"
  product_alias = "myapp"
  env_alias     = "prod"
  authorizer_info = {
    function_name         = "api-authorizer"
    handler_path          = "authorizer.handler"
    package_path          = "./authorizer"
    package_type          = "LocalZip"
    module_name           = "auth"
    environment_variables = {
      JWT_SECRET = "your-secret-key"
      API_URL    = "https://api.example.com"
    }
  }
  
  # Optional VPC configuration
  vpc_id           = "vpc-12345678"
  subnet_ids       = ["subnet-12345", "subnet-67890"]
  security_group_ids = ["sg-12345"]
  
  # Optional Lambda configuration
  timeout     = 30
  memory_size = 256
  layers      = ["arn:aws:lambda:us-west-2:123456789012:layer:my-layer:1"]
  
  tags = {
    Environment = "production"
    Project     = "myapp"
  }
}
```

## Inputs

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
| `gateway_endpoints` | List of REST API Gateway endpoints to expose (e.g., `app/test/func`, `app/check`) limitation: only three-level resource creation | `list(object)` | `[]` | no |
| `create_dynamodb_memory_table` | Enable DynamoDB table for session storage | `bool` | `false` | no |
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
| `timeout` | Authorizer Lambda timeout in seconds | `number` | `30` | no |
| `memory_size` | Authorizer Lambda memory size in MB | `number` | `128` | no |
| `layers` | List of Lambda layer ARNs to attach | `list(string)` | `[]` | no |
| `environment_variables` | Environment variables for authorizer | `map(string)` | `{}` | no |

## Outputs

| Name | Description |
|------|-------------|
| lambda_function_name | Name of the authorizer Lambda function |
| lambda_function_arn | ARN of the authorizer Lambda function |
| lambda_function_invoke_arn | Invoke ARN of the authorizer Lambda function |
| lambda_role_arn | ARN of the authorizer Lambda IAM role |
| lambda_security_group_id | ID of the authorizer Lambda security group (if created) |

## Integration with API Gateway

To use this authorizer with API Gateway:

```hcl
resource "aws_api_gateway_authorizer" "lambda_authorizer" {
  name            = "my-authorizer"
  rest_api_id     = aws_api_gateway_rest_api.api.id
  authorizer_uri  = module.authorizer.lambda_function_invoke_arn
  type            = "REQUEST"
  identity_source = "method.request.header.Authorization"
  authorizer_result_ttl_in_seconds = 300
}

resource "aws_lambda_permission" "allow_apigw_authorizer" {
  statement_id  = "AllowAPIGatewayInvokeAuthorizer"
  action        = "lambda:InvokeFunction"
  function_name = module.authorizer.lambda_function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.api.execution_arn}/*/*"
}
```
