variable "region" {
  type        = string
  description = "AWS Region"
  default     = "ap-southeast-2"
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
  description = "Module name"
}

variable "vpc_id" {
  type        = string
  description = "VPC ID for deployment"
}

variable "private_subnet_ids" {
  type        = list(string)
  description = "List of private subnet IDs"
}

variable "is_production" {
  description = "Is production environment"
  type        = bool
  default     = false
}

variable "openai_api_key" {
  description = "OpenAI API Key"
  type        = string
  sensitive   = true
}
