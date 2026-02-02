variable "product_alias" {
  type        = string
  description = "The product alias (used in ACR name and image name)"
}

variable "env_alias" {
  type        = string
  description = "The environment alias (dev, staging, d, etc.)"
}

variable "module_name" {
  type        = string
  description = "The module name (part of ACR and image name)"
}

variable "region" {
  type        = string
  description = "The Azure region to deploy to"
}

variable "resource_group_name" {
  type        = string
  description = "The Azure resource group to deploy to"
}

variable "product_display_name" {
  type        = string
  description = "The product display name"
  default     = "Demo Platform API"
}

variable "is_production" {
  type        = bool
  description = "Whether this is a production environment"
  default     = false
}

variable "package_path" {
  type        = string
  description = "The path to the package to deploy"
  default     = "dist"
}

variable "container_port" {
  type        = number
  description = "The port to expose on the container"
  default     = 8000
}

variable "container_health_check_path" {
  type        = string
  description = "The path to check for health"
  default     = "/health"
}

variable "tags" {
  type        = map(string)
  description = "Tags to apply to the resources"
  default     = {}
}

variable "api_version" {
  type        = string
  description = "The API version to use"
  default     = "v1"
}

variable "gateway_endpoints" {
  type        = list(any)
  description = "The gateway endpoints to create"
}

variable "publisher_email" {
  type        = string
  description = "The publisher email"
}

variable "environment_variables" {
  type        = map(string)
  description = "The environment variables to pass to the container"
  default     = {}
}

variable "create_redis_cluster" {
  type        = bool
  description = "Whether to create a Redis cluster"
  default     = false
}

variable "create_cosmosdb_cluster" {
  type        = bool
  description = "Whether to create a CosmosDB cluster"
  default     = false
}
variable "openai_api_key" {
  type        = string
  description = "The OpenAI API key"
}