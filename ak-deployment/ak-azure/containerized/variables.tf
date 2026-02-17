# variable "subscription_id" {
#   type        = string
#   description = "Azure subscription ID"
# }

variable "region" {
  type        = string
  description = "Azure region for resources"
}

variable "resource_group_name" {
  type        = string
  description = "Resource group name"
}

variable "product_alias" {
  type        = string
  description = "Product alias"
}

variable "env_alias" {
  type        = string
  description = "Environment alias (dev, staging, prod)"
}

variable "product_display_name" {
  type        = string
  description = "Product display name"
  default     = "An Agent Kernel deployment"
}

variable "module_name" {
  type        = string
  description = "Module name"
}

variable "package_path" {
  type        = string
  description = "Docker image source path (app root)"
}

variable "environment_variables" {
  description = "Environment variables for the container"
  type        = map(string)
  default     = {}
}

variable "api_version" {
  type        = string
  description = "API version"
  default     = "v1"
}

variable "agent_endpoint" {
  type        = string
  description = "Agent invocation endpoint"
  default     = "chat"
}

variable "api_base_path" {
  type        = string
  description = "Optional base path segment for the API (e.g., 'api'). Set to null or empty to omit."
  default     = "api"
}

variable "gateway_endpoints" {
  description = "List of HTTP API endpoints to expose. If empty, default POST endpoints are created."
  type = list(object({
    path           = string # e.g. "chat"
    method         = string # e.g. "GET", "POST", "PUT", "DELETE", "ANY"
    overwrite_path = string # backend path override, e.g. "/run"
  }))
  default = []
  validation {
    condition = alltrue([
      for ep in var.gateway_endpoints : (
        length(trimspace(ep.path)) > 0 &&
        length(trimspace(ep.method)) > 0 &&
        length(trimspace(ep.overwrite_path)) > 0 &&
        contains(["GET", "POST", "PUT", "DELETE", "PATCH", "ANY"], upper(ep.method))
      )
    ])
    error_message = "Each gateway_endpoints object must have non-empty 'path', 'method', and 'overwrite_path' fields, and 'method' must be one of: GET, POST, PUT, DELETE, PATCH, ANY."
  }
}

variable "tags" {
  type        = map(string)
  description = "Resource tags"
  default     = {}
}

# VNet Configuration
variable "vnet_cidr" {
  type        = string
  description = "CIDR block for the VNet"
  default     = "10.0.0.0/16"
}

variable "public_subnet_cidrs" {
  type        = list(string)
  description = "CIDR blocks for public subnets"
  default     = ["10.0.1.0/24", "10.0.2.0/24"]
}

variable "private_subnet_cidrs" {
  type        = list(string)
  description = "CIDR blocks for private subnets"
  default     = ["10.0.3.0/24", "10.0.4.0/24"]
}

variable "vnet_id" {
  type        = string
  description = "VNet ID. If not provided, a new VNet will be created"
  default     = null
}

variable "vnet_name" {
  type        = string
  description = "VNet name (required when using existing VNet)"
  default     = null
}

variable "vnet_resource_group_name" {
  type        = string
  description = "VNet resource group name (required when using existing VNet)"
  default     = null
}

variable "private_subnet_ids" {
  type        = list(string)
  description = "Private subnet names when using existing VNet"
  default     = null
}

# Session Storage Configuration
variable "create_redis_cluster" {
  type        = bool
  description = "Create Azure Cache for Redis for session storage"
  default     = false
}

variable "create_cosmosdb_cluster" {
  type        = bool
  description = "Create CosmosDB Table for session storage"
  default     = false
}

variable "cosmosdb_consistency_level" {
  type        = string
  description = "CosmosDB consistency level"
  default     = "Session"
}

variable "cosmosdb_public_network_access_enabled" {
  type        = bool
  description = "Enable public network access for CosmosDB"
  default     = false
}

variable "cosmosdb_point_in_time_recovery_enabled" {
  type        = bool
  description = "Enable point-in-time recovery for CosmosDB"
  default     = false
}

variable "cosmosdb_server_side_encryption_enabled" {
  type        = bool
  description = "Enable server-side encryption for CosmosDB"
  default     = true
}

variable "cosmosdb_key_vault_key_id" {
  type        = string
  description = "Key Vault key ID for CosmosDB encryption"
  default     = null
}

variable "container_min_replicas" {
  type        = number
  description = "Minimum number of container replicas"
  default     = 1
  validation {
    condition     = var.container_min_replicas >= 0 && var.container_min_replicas <= 300
    error_message = "container_min_replicas must be between 0 and 300"
  }
}

variable "container_max_replicas" {
  type        = number
  description = "Maximum number of container replicas"
  default     = 10
  validation {
    condition     = var.container_max_replicas >= 1 && var.container_max_replicas <= 300
    error_message = "container_max_replicas must be between 1 and 300"
  }
}

variable "container_port" {
  type        = number
  description = "Container port exposed by the application"
  default     = 8000
}

variable "container_health_check_path" {
  type        = string
  description = "Health check path for container probes"
  default     = "/health"
}

variable "container_scale_concurrent_requests" {
  type        = number
  description = "Number of concurrent requests to trigger scaling"
  default     = 10
}

# API Management Configuration
variable "publisher_name" {
  type        = string
  description = "API Management publisher name"
  default     = "Agent Kernel"
}

variable "publisher_email" {
  type        = string
  description = "API Management publisher email"
}

variable "is_production" {
  type        = bool
  description = "Whether this is a production environment"
  default     = false
}
