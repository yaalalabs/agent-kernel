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
  # sensitive   = true
}