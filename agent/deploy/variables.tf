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
  sensitive   = true
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
