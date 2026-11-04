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

variable "vpc_id" {
  description = "VPC ID for ECS deployment. If null, the weekly integration base deployment's VPC is reused"
  type        = string
  default     = null
}

variable "private_subnet_ids" {
  description = "Private subnet IDs for ECS deployment. If null, the base deployment's private subnets are reused"
  type        = list(string)
  default     = null
}

variable "openai_api_key" {
  description = "OpenAI API Key"
  type        = string
}

variable "langfuse_secret_key" {
  description = "Langfuse secret Key"
  type        = string
}

variable "langfuse_public_key" {
  description = "Langfuse public Key"
  type        = string
}

variable "langfuse_base_url" {
  description = "Langfuse base url"
  type        = string
  default     = "https://cloud.langfuse.com"
}
