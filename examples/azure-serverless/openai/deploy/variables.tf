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

variable "module_type" {
  type        = string
  description = "Module type (python or nodejs)"
  default     = "python"
  validation {
    condition     = contains(["python", "nodejs"], var.module_type)
    error_message = "Module type must be either 'python' or 'nodejs'."
  }
}

variable "publisher_email" {
  type        = string
  description = "Publisher email for the API Management"
}

variable "gateway_endpoints" {
  description = "List of REST API endpoints to expose with their target functions"
  type = list(object({
    function_name = string 
    path          = string 
    method        = string 
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

variable "create_redis_cluster" {
  type        = bool
  description = "Create a redis cluster to store Agent memory"
  default     = true
}

variable "create_cosmosdb_cluster" {
  type        = bool
  description = "Create a cosmosdb cluster to store Agent memory"
  default     = false
}

variable "resource_group_name" {
  type        = string
  description = "Resource group name"
}