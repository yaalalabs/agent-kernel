variable "project_id" {
  type        = string
  description = "GCP project ID"
}

variable "region" {
  type        = string
  description = "GCP region"
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

variable "module_name" {
  type        = string
  description = "Module name"
}

variable "is_production" {
  type        = bool
  description = "Is production"
  default     = false
}

variable "package_path" {
  type        = string
  description = "Docker image source path (app root)"
}

variable "environment_variables" {
  type        = map(string)
  description = "Environment variables for the container"
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
  description = "Base path for the API"
  default     = "api"
}

variable "tags" {
  type        = map(string)
  description = "Resource labels"
  default     = {}
}

# Cloud Run settings
variable "cpu" {
  type        = string
  description = "CPU allocation (e.g. '1' = 1 vCPU, '2' = 2 vCPUs)"
  default     = "1"
}

variable "memory" {
  type        = string
  description = "Memory allocation (e.g. '512Mi', '1Gi')"
  default     = "512Mi"
}

variable "min_instance_count" {
  type        = number
  description = "Minimum number of instances (0 = scale to zero)"
  default     = 0
}

variable "max_instance_count" {
  type        = number
  description = "Maximum number of instances"
  default     = 10
}

variable "container_port" {
  type        = number
  description = "Port the container listens on"
  default     = 8000
}

variable "health_check_endpoint" {
  type        = string
  description = "Health check path"
  default     = "/health"
}

variable "connector_cidr" {
  type        = string
  description = "CIDR block for the VPC Access Connector (e.g. '10.9.0.0/28')"
  default     = "10.9.0.0/28"
}

# Network
variable "network_id" {
  type        = string
  description = "VPC network ID. If null, a new VPC is created"
  default     = null
}

variable "private_subnet_id" {
  type        = string
  description = "Private subnet ID (when using existing VPC)"
  default     = null
}

variable "public_subnet_cidr" {
  type        = string
  description = "CIDR for public subnet"
  default     = "10.0.1.0/24"
}

variable "private_subnet_cidr" {
  type        = string
  description = "CIDR for private subnet"
  default     = "10.0.2.0/24"
}

# Storage backends
variable "create_redis_cluster" {
  type        = bool
  description = "Create a Memorystore Redis instance for agent memory"
  default     = false
}

variable "create_firestore_database" {
  type        = bool
  description = "Create a Firestore database for agent session storage"
  default     = false
}

variable "gateway_endpoints" {
  description = "Additional API endpoints to expose"
  type = list(object({
    path           = string
    method         = string
    overwrite_path = string
  }))
  default = []
  validation {
    condition = alltrue([
      for ep in var.gateway_endpoints : (
        length(trimspace(ep.path)) > 0 &&
        length(trimspace(ep.method)) > 0 &&
        length(trimspace(ep.overwrite_path)) > 0 &&
        contains(
          ["GET", "POST", "PUT", "DELETE", "PATCH", "ANY", "$default"],
          upper(ep.method)
        )
      )
    ])
    error_message = "Each endpoint must have non-empty path, method, and overwrite_path. Method must be GET, POST, PUT, DELETE, PATCH, ANY, or $default."
  }
}

variable "enable_mcp_server" {
  type        = bool
  description = "Enable MCP server and expose MCP API endpoint"
  default     = false
}

# CORS configuration.
# GCP API Gateway does not have native CORS handling like AWS API Gateway v2.
# When enable_cors = true, an OPTIONS pre-flight handler is added to the OpenAPI
# spec so the gateway responds to browser pre-flight requests.
# The actual CORS response headers (Access-Control-Allow-*) must be set by your
# Cloud Run application (via FastAPI middleware or similar).
variable "enable_cors" {
  type        = bool
  description = "Enable CORS pre-flight OPTIONS handling in the API Gateway"
  default     = true
}

variable "cors_allow_origins" {
  type        = list(string)
  description = "CORS allowed origins (used as documentation; enforce in Cloud Run app)"
  default     = ["*"]
}

variable "cors_allow_methods" {
  type        = list(string)
  description = "CORS allowed methods"
  default     = ["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"]
}

variable "cors_allow_headers" {
  type        = list(string)
  description = "CORS allowed headers"
  default     = ["*"]
}

variable "cors_expose_headers" {
  type        = list(string)
  description = "CORS exposed headers"
  default     = []
}

variable "cors_max_age" {
  type        = number
  description = "CORS pre-flight cache max age in seconds"
  default     = 600
}

variable "cors_allow_credentials" {
  type        = bool
  description = "Whether to allow credentials in CORS requests"
  default     = false
}

# Throttling — rate limiting for the API Gateway.
# GCP API Gateway supports quota-based throttling via x-google-quota in the OpenAPI spec.
# For production rate limiting, consider Cloud Armor policies on the load balancer.
# Both values must be provided to enable throttling (set null to disable).
variable "throttling_rate_limit" {
  type        = number
  description = "Steady-state request rate limit per second. Set null to disable."
  default     = null
}

variable "throttling_burst_limit" {
  type        = number
  description = "Burst request limit (token bucket size). Set null to disable."
  default     = null
}
