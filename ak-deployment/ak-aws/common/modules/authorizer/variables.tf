variable "region" {
  type        = string
  description = "AWS region"
}

variable "product_alias" {
  type        = string
  description = "Product alias"
}

variable "env_alias" {
  type        = string
  description = "Environment alias"
}

variable "authorizer_function_name" {
  type        = string
  description = "Authorizer Lambda function name"
}

variable "authorizer_function_description" {
  type        = string
  description = "Authorizer Lambda function description"
  default     = "API Gateway Lambda Authorizer"
}

variable "authorizer_handler_path" {
  type        = string
  description = "Lambda authorizer handler path"
}

variable "authorizer_package_path" {
  type        = string
  description = "Authorizer Lambda package path or Docker image source path"
}

variable "authorizer_package_type" {
  type        = string
  description = "Authorizer Lambda deployment type Image/LocalZip/S3Zip"
  default     = "LocalZip"
}

variable "authorizer_module_name" {
  type        = string
  description = "Authorizer module name"
}

variable "authorizer_environment_variables" {
  description = "Authorizer Lambda environment variables"
  type        = map(string)
  default     = {}
}

variable "authorizer_result_ttl_in_seconds" {
  type        = number
  description = "Authorizer result TTL in seconds"
  default     = 150
}

variable "module_type" {
  type        = string
  description = "Module type"
  default     = "python"
}

variable "timeout" {
  description = "Lambda timeout"
  type        = number
  default     = 30
}

variable "memory_size" {
  description = "Lambda memory size"
  type        = number
  default     = 128
}

variable "layers" {
  description = "Lambda layers"
  type        = list(string)
  default     = []
}

variable "tags" {
  type        = map(string)
  description = "Resource tags"
  default     = {}
}

variable "vpc_id" {
  type        = string
  description = "VPC ID"
  default     = null
}

variable "subnet_ids" {
  type        = list(string)
  description = "VPC subnet IDs for Lambda"
  default     = []
}

variable "security_group_ids" {
  type        = list(string)
  description = "Security group IDs for Lambda"
  default     = []
}

variable "is_production" {
  description = "Is production"
  type        = bool
  default     = false
}

variable "lambda_kms_key_arn" {
  type        = string
  description = "KMS key ARN for Lambda encryption"
  default     = null
}

variable "cloudwatch_kms_key_arn" {
  type        = string
  description = "KMS key ARN for CloudWatch logs encryption"
  default     = null
}

variable "lambda_signer_profile_name" {
  type        = string
  description = "AWS Signer profile name"
  default     = "sample_profile"
}

variable "lambda_signing_config_arn" {
  type        = string
  description = "Lambda code signing configuration ARN"
  default     = null
}