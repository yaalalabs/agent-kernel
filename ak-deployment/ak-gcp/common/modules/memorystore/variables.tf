variable "project_id" {
  type        = string
  description = "GCP project ID"
}

variable "region" {
  type        = string
  description = "GCP region"
  default     = "us-central1"
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

variable "network_id" {
  type        = string
  description = "VPC network ID for the Redis instance"
}

variable "tier" {
  type        = string
  description = "Service tier: BASIC (no replication) or STANDARD_HA (high availability)"
  default     = "BASIC"
}

variable "memory_size_gb" {
  type        = number
  description = "Redis memory size in GB"
  default     = 1
}

variable "redis_version" {
  type        = string
  description = "Redis version"
  default     = "REDIS_7_0"
}

variable "auth_enabled" {
  type        = bool
  description = "Enable Redis AUTH for password-based access"
  default     = true
}

variable "tags" {
  type        = map(string)
  description = "Resource labels"
  default     = {}
}
