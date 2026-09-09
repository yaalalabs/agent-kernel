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

variable "authorizer_info" {
  description = "Authorizer configuration object"
  type = object({
    description           = optional(string, "API Gateway Lambda Authorizer")
    function_name         = string
    handler_path          = string
    package_path          = string
    package_type          = string
    module_name           = string
    result_ttl_in_seconds = optional(number, 150)
    timeout               = optional(number, 30)
    memory_size           = optional(number, 128)
    layers                = optional(list(string), [])
    environment_variables = optional(map(string), {})
  })
}

variable "module_type" {
  type        = string
  description = "Module type"
  default     = "python"
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