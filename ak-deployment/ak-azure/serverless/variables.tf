variable "region" {
  type        = string
  description = "Azure region (e.g., eastus, westus2)"
}

variable "resource_group_name" {
  type        = string
  description = "Name of the Azure resource group"
}

variable "product_alias" {
  type        = string
  description = "Product alias"
}

variable "env_alias" {
  type        = string
  description = "Environment alias"
}

variable "product_display_name" {
  type        = string
  description = "Product display name"
  default     = "An Agent Kernel deployment"
}

variable "module_type" {
  type        = string
  description = "Module type (python or nodejs)"
  default     = "python"
  validation {
    condition     = contains(["python", "nodejs"], var.module_type)
    error_message = "Module type must be either 'python' or 'nodejs'."
  }
}

variable "module_name" {
  type        = string
  description = "Module name"
}

variable "is_production" {
  description = "Is production environment"
  type        = bool
  default     = false
}

variable "package_path" {
  type        = string
  description = "Local path to the zip package"
}

variable "environment_variables" {
  description = "Environment variables for the function app"
  type        = map(string)
  default     = {}
}

variable "function_name" {
  description = "Function name"
  type        = string
}

variable "function_description" {
  description = "Function description"
  type        = string
  default     = ""
}

variable "api_version" {
  type        = string
  description = "API version"
  default     = "v1"
}

variable "agent_endpoint" {
  type        = string
  description = "Agent invocation endpoint"
  default     = "HttpExample"
}

variable "api_base_path" {
  type        = string
  description = "Optional base path segment for the API (e.g., 'api'). Set to null or empty to omit."
  default     = "api"
}

variable "tags" {
  type        = map(string)
  description = "Resource tags"
  default     = {}
}


variable "redis_connection_url" {
  type        = string
  description = "Redis connection URL (e.g., rediss://:password@hostname:port). Pass from Redis module."
  default     = null
}

variable "create_cosmosdb_cluster" {
  type        = bool
  description = "Create a Cosmos DB cluster to store Agent memory"
  default     = true
}

variable "cosmosdb_table_name" {
  type        = string
  description = "Cosmos DB table name for agent memory. Pass from Cosmos DB module."
  default     = null
}

variable "cosmosdb_connection_string" {
  type        = string
  description = "Cosmos DB connection string. Pass from Cosmos DB module."
  default     = null
  sensitive   = true
}

variable "cosmosdb_consistency_level" {
  type        = string
  description = "Consistency level: Strong, BoundedStaleness, Session, ConsistentPrefix, Eventual"
  default     = "Session"
  validation {
    condition     = contains(["Strong", "BoundedStaleness", "Session", "ConsistentPrefix", "Eventual"], var.cosmosdb_consistency_level)
    error_message = "Invalid consistency level"
  }
}

variable "cosmosdb_public_network_access_enabled" {
  type        = bool
  description = "Enable public network access"
  default     = true
}

variable "cosmosdb_point_in_time_recovery_enabled" {
  type        = bool
  description = "Enable continuous backup (Point-in-Time Recovery)"
  default     = false
}

variable "cosmosdb_server_side_encryption_enabled" {
  type        = bool
  description = "Enable customer-managed encryption key (encryption is always on by default)"
  default     = false
}

variable "cosmosdb_key_vault_key_id" {
  type        = string
  description = "Key Vault key ID for customer-managed encryption"
  default     = null
}

variable "gateway_endpoints" {
  description = "List of REST API endpoints to expose with their target functions"
  type = list(object({
    function_name = string # e.g. "ak-api", "health-service"
    path          = string # e.g. "/check", "/health", "/chat
    method        = string # GET, POST, PUT, DELETE, PATCH, ANY
  }))
  validation {
    condition = alltrue([
      for ep in var.gateway_endpoints : (
        length(trimspace(ep.path)) > 0 &&
        length(trimspace(ep.function_name)) > 0 &&
        contains(
          ["GET", "POST", "PUT", "DELETE", "PATCH", "ANY"],
          upper(ep.method)
        )
      )
    ])
    error_message = "Each gateway_endpoints entry must have: a non-empty 'function_name', a non-empty 'path', and a valid HTTP method (GET, POST, PUT, DELETE, PATCH, ANY)"
  }
}

variable "publisher_name" {
  type        = string
  description = "API Management publisher name"
  default     = "Your Organization"
}

variable "publisher_email" {
  type        = string
  description = "API Management publisher email"
}

variable "apim_sku_name" {
  type        = string
  description = "API Management SKU (Developer, Basic, Standard, Premium, Consumption)"
  default     = "Consumption_0"
  validation {
    condition     = can(regex("^(Developer|Basic|Standard|Premium|Consumption)_\\d+$", var.apim_sku_name))
    error_message = "APIM SKU must be in format: Developer_1, Consumption_0, etc."
  }
}

variable "vnet_id" {
  type        = string
  description = "VNet ID"
  default     = null
}

variable "private_subnet_ids" {
  type = list(string)
  description = "When using an existing VPC to deploy, private subnet IDs need to be provided"
  default     = null
}

variable "vnet_name" {
  type        = string
  description = "VNet name"
  default     = null
}

variable "vnet_resource_group_name" {
  type        = string
  description = "VNet resource group name"
  default     = null
}

variable "vnet_cidr" {
  type        = string
  description = "VNet CIDR"
  default     = "10.0.0.0/16"
}

variable "sku_name_redis" {
  type        = string
  description = "Redis SKU name (Basic, Standard, or Premium)"
  default     = "Basic" // for subnet binding we need a premium tier

  validation {
    condition     = contains(["Basic", "Standard", "Premium"], var.sku_name_redis)
    error_message = "SKU must be Basic, Standard, or Premium"
  }

}

variable "redis_node_family" {
  type        = string
  description = "Redis family (C for Basic/Standard, P for Premium)"
  default     = "P"
  
  validation {
    condition     = contains(["C", "P"], var.redis_node_family)
    error_message = "Family must be C (Basic/Standard) or P (Premium)"
  }
  
}

variable "azure_encryption_key_id" {
  type        = string
  default     = null
  description = "Full Azure Key Vault Key ID"
}

variable "package_type" {
  type        = string
  description = "Lambda deployment type Image/LocalZip/S3Zip"
  default     = "LocalZip"

  validation {
    condition     = contains(["Image", "LocalZip"], var.package_type)
    error_message = "Package type must be either 'Image', 'LocalZip', or 'S3Zip'."
  }

}

variable "create_redis_cluster" {
  type        = bool
  description = "Create a redis cluster to store Agent memory"
  default     = true

}

variable "private_subnet_cidrs" {
  type = list(string)
  description = "CIDR blocks for the private subnets"
  default = ["10.0.3.0/24", "10.0.4.0/24"]
}

variable "public_subnet_cidrs" {
  type = list(string)
  description = "CIDR blocks for the public subnets"
  default = ["10.0.1.0/24", "10.0.2.0/24"]
}

variable "create_custom_storage_account" {
  type        = bool
  description = "Create a custom storage account to store custom data"
  default     = false
}