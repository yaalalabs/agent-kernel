# Agent Kernel Infrastructure and Deployment Setup

This repository contains Terraform modules for deploying AWS API Gateway and Lambda functions, along with examples of how to use them together.

## Modules

### API Gateway Module

The API Gateway module creates an AWS API Gateway REST API with a resource and method that integrates with an AWS Lambda function.

#### Usage

```hcl
module "api_gateway" {
  source = "github.com/your-org/terraform-aws-api-lambda//modules/api_gateway"

  api_name        = "my-api"
  api_description = "My API Gateway"
  resource_path   = "resource"
  http_method     = "POST"

  lambda_invoke_arn    = module.lambda_function.invoke_arn
  lambda_function_name = module.lambda_function.function_name

  tags = {
    Environment = "dev"
    Project     = "my-project"
  }
}
```

#### Inputs

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|----------|
| api_name | Name of the API Gateway | string | n/a | yes |
| api_description | Description of the API Gateway | string | "API Gateway created by Terraform" | no |
| resource_path | Path part for the API Gateway resource | string | "resource" | no |
| http_method | HTTP method for the API Gateway method | string | "POST" | no |
| authorization_type | Authorization type for the API Gateway method | string | "NONE" | no |
| lambda_invoke_arn | ARN of the Lambda function to invoke | string | n/a | yes |
| lambda_function_name | Name of the Lambda function | string | n/a | yes |
| stage_name | Name of the deployment stage | string | "dev" | no |
| tags | Tags to apply to resources | map(string) | {} | no |

#### Outputs

| Name | Description |
|------|-------------|
| api_id | ID of the API Gateway REST API |
| api_name | Name of the API Gateway REST API |
| resource_id | ID of the API Gateway Resource |
| resource_path | Path of the API Gateway Resource |
| invoke_url | Invoke URL for the API Gateway |
| execution_arn | Execution ARN of the API Gateway |
| stage_name | Name of the API Gateway stage |

### Lambda Module

The Lambda module creates an AWS Lambda function with the necessary IAM roles and permissions.

#### Usage

```hcl
module "lambda_function" {
  source = "github.com/your-org/terraform-aws-api-lambda//modules/lambda"

  lambda_role_name  = "my-lambda-role"
  function_name     = "my-function"
  description       = "My Lambda function"
  lambda_source_dir = "../lambda_function"
  lambda_zip_path   = "${path.module}/lambda_function.zip"

  environment_variables = {
    ENVIRONMENT = "dev"
  }

  tags = {
    Environment = "dev"
    Project     = "my-project"
  }
}
```

#### Inputs

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|----------|
| lambda_role_name | Name of the IAM role for the Lambda function | string | n/a | yes |
| function_name | Name of the Lambda function | string | n/a | yes |
| description | Description of the Lambda function | string | "Lambda function created by Terraform" | no |
| handler | Handler for the Lambda function | string | "lambda_function.lambda_handler" | no |
| runtime | Runtime for the Lambda function | string | "python3.9" | no |
| lambda_source_dir | Directory containing the Lambda function source code | string | n/a | yes |
| lambda_zip_path | Path where the Lambda function ZIP file will be created | string | "lambda_function.zip" | no |
| timeout | Timeout for the Lambda function in seconds | number | 30 | no |
| memory_size | Memory size for the Lambda function in MB | number | 128 | no |
| environment_variables | Environment variables for the Lambda function | map(string) | {} | no |
| additional_policy_statements | Additional IAM policy statements to add to the Lambda function role | list(any) | [] | no |
| log_retention_days | Number of days to retain Lambda function logs | number | 14 | no |
| tags | Tags to apply to resources | map(string) | {} | no |

#### Outputs

| Name | Description |
|------|-------------|
| function_name | Name of the Lambda function |
| function_arn | ARN of the Lambda function |
| invoke_arn | Invoke ARN of the Lambda function |
| role_name | Name of the IAM role for the Lambda function |
| role_arn | ARN of the IAM role for the Lambda function |
| log_group_name | Name of the CloudWatch log group for the Lambda function |

## Examples

### API Gateway with Lambda Function

This example demonstrates how to use the API Gateway and Lambda modules together to create a REST API backed by a Lambda function.

To run the example:

1. Clone the repository
2. Navigate to the `examples/api_lambda` directory
3. Update the `terraform.tfvars` file with your desired values
4. Run `terraform init` and `terraform apply`

## Requirements

- Terraform >= 0.13.0
- AWS provider >= 3.0.0

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Publishing

This repository is set up to be published as a Terraform module. The following sections describe how to publish a new version of the module.

### Prerequisites

- [Terraform](https://www.terraform.io/downloads.html) >= 0.13.0
- [terraform-docs](https://terraform-docs.io/user-guide/installation/) >= 0.13.0
- [Git](https://git-scm.com/downloads) >= 2.0.0

### Publishing Process

1. Make your changes to the module
2. Update the CHANGELOG.md file with your changes
3. Run the validation script to ensure the module is valid:
   ```bash
   ./scripts/validate.sh
   ```
4. Create a new release:
   ```bash
   ./scripts/release.sh v1.0.0
   ```
   Replace `v1.0.0` with the version you want to release
5. Push the changes and tags to GitHub:
   ```bash
   git push && git push --tags
   ```

### Module Structure

The module follows the standard Terraform module structure:

```
.
├── CHANGELOG.md
├── README.md
├── examples/
│   └── api_lambda/
│       ├── main.tf
│       ├── terraform.tfvars
│       └── variables.tf
├── lambda_function/
│   └── lambda_function.py
├── modules/
│   ├── api_gateway/
│   │   ├── main.tf
│   │   ├── outputs.tf
│   │   ├── variables.tf
│   │   └── versions.tf
│   └── lambda/
│       ├── main.tf
│       ├── outputs.tf
│       ├── variables.tf
│       └── versions.tf
├── scripts/
│   ├── generate-docs.sh
│   ├── release.sh
│   └── validate.sh
├── tests/
│   ├── api_gateway_test.sh
│   └── lambda_test.sh
└── versions.tf
```
