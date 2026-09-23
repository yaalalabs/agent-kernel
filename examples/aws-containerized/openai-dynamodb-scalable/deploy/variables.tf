variable "region" {
  type        = string
  description = "Region"
}

variable "prefix" {
  type        = string
  description = "Prefix applied to every resource name"
}

variable "is_production" {
  description = "Is production"
  type        = bool
  default     = false
}

variable "openai_api_key" {
  description = "OpenAI API Key. Leave empty to resolve it from SSM Parameter Store at /ak/<prefix>/openai_api_key"
  type        = string
  default     = ""
}

variable "vpc_id" {
  description = "VPC ID for ECS deployment"
  type        = string
}

variable "private_subnet_ids" {
  description = "List of private subnet IDs for ECS deployment"
  type        = list(string)
}