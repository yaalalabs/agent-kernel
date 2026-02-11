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
  source = "../../common/modules/authorizer"
  
  region                          = "us-west-2"
  product_alias                   = "myapp"
  env_alias                       = "prod"
  authorizer_function_name        = "api-authorizer"
  authorizer_handler_path         = "authorizer.handler"
  authorizer_package_path         = "./authorizer"
  authorizer_package_type         = "LocalZip"
  authorizer_module_name          = "auth"
  authorizer_environment_variables = {
    JWT_SECRET = "your-secret-key"
    API_URL    = "https://api.example.com"
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
|------|-------------|------|---------|----------|
| region | AWS region | `string` | n/a | yes |
| product_alias | Product alias | `string` | n/a | yes |
| env_alias | Environment alias | `string` | n/a | yes |
| authorizer_function_name | Authorizer Lambda function name | `string` | n/a | yes |
| authorizer_handler_path | Lambda authorizer handler path | `string` | n/a | yes |
| authorizer_package_path | Authorizer Lambda package path or Docker image source path | `string` | n/a | yes |
| authorizer_package_type | Authorizer Lambda deployment type Image/LocalZip/S3Zip | `string` | `"LocalZip"` | no |
| authorizer_module_name | Authorizer module name | `string` | n/a | yes |
| authorizer_function_description | Authorizer Lambda function description | `string` | `"API Gateway Lambda Authorizer"` | no |
| authorizer_environment_variables | Authorizer Lambda environment variables | `map(string)` | `{}` | no |
| authorizer_result_ttl_in_seconds | Authorizer result TTL in seconds | `number` | `150` | no |
| module_type | Module type | `string` | `"python"` | no |
| timeout | Lambda timeout | `number` | `30` | no |
| memory_size | Lambda memory size | `number` | `128` | no |
| layers | Lambda layers | `list(string)` | `[]` | no |
| tags | Resource tags | `map(string)` | `{}` | no |
| vpc_id | VPC ID | `string` | `null` | no |
| subnet_ids | VPC subnet IDs for Lambda | `list(string)` | `[]` | no |
| security_group_ids | Security group IDs for Lambda | `list(string)` | `[]` | no |
| is_production | Is production | `bool` | `false` | no |
| lambda_kms_key_arn | KMS key ARN for Lambda encryption | `string` | `null` | no |
| cloudwatch_kms_key_arn | KMS key ARN for CloudWatch logs encryption | `string` | `null` | no |
| lambda_signer_profile_name | AWS Signer profile name | `string` | `"sample_profile"` | no |
| lambda_signing_config_arn | Lambda code signing configuration ARN | `string` | `null` | no |

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

## Authorizer Lambda Function

Your authorizer Lambda function should follow the API Gateway Lambda authorizer format. Here's an example in Python:

```python
import json
import jwt

def handler(event, context):
    try:
        # Extract token from Authorization header
        token = event['headers'].get('Authorization', '').replace('Bearer ', '')
        
        # Verify JWT token
        decoded = jwt.decode(token, 'your-secret-key', algorithms=['HS256'])
        
        # Generate IAM policy
        effect = 'Allow'
        resource = event['methodArn']
        
        policy = {
            'principalId': decoded['user_id'],
            'policyDocument': {
                'Version': '2012-10-17',
                'Statement': [
                    {
                        'Action': 'execute-api:Invoke',
                        'Effect': effect,
                        'Resource': resource
                    }
                ]
            },
            'context': {
                'user_id': decoded['user_id'],
                'username': decoded['username']
            }
        }
        
        return policy
        
    except Exception as e:
        return {
            'principalId': 'anonymous',
            'policyDocument': {
                'Version': '2012-10-17',
                'Statement': [
                    {
                        'Action': 'execute-api:Invoke',
                        'Effect': 'Deny',
                        'Resource': event['methodArn']
                    }
                ]
            }
        }
```