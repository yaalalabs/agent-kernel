variable "region" {
  type        = string
  description = "Region"
}

variable "product_alias" {
  type        = string
  description = "Product alias"
}

variable "env_alias" {
  type        = string
  description = "Environment alias"
}

variable "module_name" {
  type        = string
  description = "module name"
}

variable "is_production" {
  description = "Is production"
  type        = bool
  default     = false
}

variable "openai_api_key" {
  description = "OpenAI API Key"
  type        = string
}

variable "vpc_id" {
  description = "VPC ID for Lambda deployment"
  type        = string
}

variable "private_subnet_ids" {
  description = "List of private subnet IDs for Lambda deployment"
  type        = list(string)
  sensitive   = true
}

variable "request_handler_lambda_package_s3" {
  description = "External Lambda artifact for request handler"
  type = object({
    bucket = string
    key    = string
  })
  default = null
}

variable "response_handler_lambda_package_s3" {
  description = "External Lambda artifact for response handler"
  type = object({
    bucket = string
    key    = string
  })
  default = null
}

variable "agent_runner_ecr_image_uri" {
  description = "External ECR image URI for agent runner"
  type        = string
  default     = null
}