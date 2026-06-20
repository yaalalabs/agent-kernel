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
  description = "Environment variables"
  type        = any
  default = {}
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
  description = "List of HTTP API endpoints to expose. If empty, a default POST /api/{api_version}/{agent_endpoint} endpoint is created."
  type = list(object({
    path = string        # The URL path segment that clients will access (e.g., "chat", "users", "webhook"). This becomes part of the full URL: https://your-domain.com/{api_base_path}/{api_version}/{path}
    method = string        # HTTP method for this endpoint (e.g., "GET", "POST", "PUT", "DELETE", "ANY"). "ANY" accepts all HTTP methods. "$default" is a special catch-all route.
    overwrite_path = string # The backend path that the ALB forwards requests to (e.g., "/api/v1/chat", "/internal/webhook"). This allows mapping external paths to different internal service endpoints.
  }))
  default = []
  validation {
    condition = alltrue([
      for ep in var.gateway_endpoints : (
        length(trimspace(ep.path)) > 0 &&
        length(trimspace(ep.method)) > 0 &&
        length(trimspace(ep.overwrite_path)) > 0 &&
        contains(["GET", "POST", "PUT", "DELETE", "PATCH", "ANY", "$default"], upper(ep.method))
      )
    ])
    error_message = "Each gateway_endpoints object must have non-empty 'path', 'method', and 'overwrite_path' fields, and 'method' must be one of: GET, POST, PUT, DELETE, PATCH, ANY, $default."
  }
}

variable "tags" {
  type = map(string)
  description = "Resource tags"
  default = {}
}

variable "vpc_cidr" {
  type        = string
  description = "CIDR block for the VPC"
  default     = "10.0.0.0/16"
}

variable "public_subnet_cidrs" {
  type = list(string)
  description = "CIDR blocks for the public subnets"
  default = ["10.0.1.0/24", "10.0.2.0/24"]
}

variable "private_subnet_cidrs" {
  type = list(string)
  description = "CIDR blocks for the private subnets"
  default = ["10.0.3.0/24", "10.0.4.0/24"]
}

variable "vpc_id" {
  type        = string
  description = "VPC ID. If not provided, a new one will be created"
  default     = null
}

variable "private_subnet_ids" {
  type = list(string)
  description = "When using an existing VPC to deploy, private subnet IDs need to be provided"
  default     = null
}

variable "create_redis_cluster" {
  type        = bool
  description = "Agent memory type. Accepted values are redis or in_memory"
  default     = false
}

variable "create_dynamodb_memory_table" {
  type        = bool
  description = "Create a dynamodb table to store the Agent memory"
  default     = false
}

# ---------------------------------------------------------------------------
# REST Service Configuration
# ---------------------------------------------------------------------------

variable "rest_service" {
  description = "REST service configuration object"
  type = object({
    cpu                   = optional(number, 256)
    memory                = optional(number, 512)
    desired_count         = optional(number, 1)
    container_port        = optional(number, 8000)
    health_check_endpoint = optional(string, "/health")
    image_uri             = optional(string, null)  # Defaults to package_path Docker image
    command               = optional(list(string), null)
    environment_variables = optional(map(string), {})
  })
  default = {
    cpu                   = 256
    memory                = 512
    desired_count         = 1
    container_port        = 8000
    health_check_endpoint = "/health"
    image_uri             = null
    command               = null
    environment_variables = {}
  }
}

variable "container_type" {
  type        = string
  description = "Container type (ECS or EKS)"
  default     = "ecs"
  validation {
    condition     = contains(["ecs", "eks"], lower(var.container_type))
    error_message = "Container type must be either 'ecs' or 'eks'."
  }
}

# CORS configuration for HTTP API (API Gateway v2)
variable "enable_cors" {
  type        = bool
  description = "Enable CORS on the HTTP API"
  default     = true
}

variable "cors_allow_origins" {
  type        = list(string)
  description = "CORS allowed origins"
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
  description = "CORS max age in seconds"
  default     = 600
}

variable "cors_allow_credentials" {
  type        = bool
  description = "Whether to allow credentials for CORS"
  default     = false
}

# Stage throttling (default route settings)
# Both values must be provided to enable throttling block.
variable "throttling_rate_limit" {
  type        = number
  description = "Steady-state rate limit (requests per second) for default route. Set null to disable."
  default     = null
}

variable "throttling_burst_limit" {
  type        = number
  description = "Burst limit (token bucket size) for default route. Set null to disable."
  default     = null
}

variable "enable_mcp_server" {
  type        = bool
  description = "Enable MCP server and expose MCP API endpoint"
  default     = false
}

data "aws_ecr_authorization_token" "token" {}
data "aws_caller_identity" "current" {}

# ---------------------------------------------------------------------------
# Queue Mode Configuration
# ---------------------------------------------------------------------------

variable "enable_queue_mode" {
  type        = bool
  description = "Enable SQS queue mode. Creates Input/Output queues, DynamoDB response store, and Agent Runner ECS service."
  default     = false
}

variable "queue_mode_type" {
  type        = string
  description = "Queue mode type: 'sync' (client waits on same connection) or 'async' (client polls a separate GET endpoint)."
  default     = "sync"
  validation {
    condition     = contains(["sync", "async"], var.queue_mode_type)
    error_message = "queue_mode_type must be either 'sync' or 'async'."
  }
}

# --- Queue Configuration Object ---

variable "queue_config" {
  description = "Queue configuration object"
  type = object({
    # Queue names
    input_queue_name  = optional(string, "input-queue")  # Queue name suffix
    output_queue_name = optional(string, "output-queue") # Queue name suffix

    # Shared settings
    sqs_managed_sse_enabled   = optional(bool, true)
    max_message_size          = optional(number, 262144)  # 256 KB
    receive_wait_time_seconds = optional(number, 0)

    # Input queue settings
    input_queue_visibility_timeout            = optional(number, 60)
    input_queue_message_retention_seconds     = optional(number, 1800)  # 30 minutes
    input_queue_max_receive_count             = optional(number, 5)
    input_queue_create_dlq                    = optional(bool, false)
    input_queue_dlq_message_retention_seconds = optional(number, 1800)

    # Output queue settings
    output_queue_visibility_timeout            = optional(number, 60)
    output_queue_message_retention_seconds     = optional(number, 1800)
    output_queue_max_receive_count             = optional(number, 5)
    output_queue_create_dlq                    = optional(bool, false)
    output_queue_dlq_message_retention_seconds = optional(number, 1800)
  })
  default = {
    input_queue_name                          = "input-queue"
    output_queue_name                         = "output-queue"
    sqs_managed_sse_enabled                   = true
    max_message_size                          = 262144
    receive_wait_time_seconds                 = 0
    input_queue_visibility_timeout            = 60
    input_queue_message_retention_seconds     = 1800
    input_queue_max_receive_count             = 5
    input_queue_create_dlq                    = false
    input_queue_dlq_message_retention_seconds = 1800
    output_queue_visibility_timeout            = 60
    output_queue_message_retention_seconds     = 1800
    output_queue_max_receive_count             = 5
    output_queue_create_dlq                    = false
    output_queue_dlq_message_retention_seconds = 1800
  }
}

# --- Agent Runner Configuration Object ---

variable "agent_runner" {
  description = "Agent runner configuration object"
  type = object({
    cpu                   = optional(number, 512)
    memory                = optional(number, 1024)
    desired_count         = optional(number, 1)
    package_path          = optional(string, null)  # Path to agent runner Docker source (builds separate image)
    image_uri             = optional(string, null)  # Or provide pre-built image URI
    command               = optional(list(string), null)
    environment_variables = optional(map(string), {})
  })
  default = {
    cpu                   = 512
    memory                = 1024
    desired_count         = 1
    package_path          = null
    image_uri             = null
    command               = null
    environment_variables = {}
  }
}

# --- Scaling Configuration Object ---

variable "scaling_config" {
  description = "Auto scaling configuration object for agent runner"
  type = object({
    enabled            = optional(bool, false)
    min_count          = optional(number, 0)
    max_count          = optional(number, 10)
    backlog_target     = optional(number, 10)
    scale_in_cooldown  = optional(number, 120)
    scale_out_cooldown = optional(number, 30)
  })
  default = {
    enabled            = false
    min_count          = 0
    max_count          = 10
    backlog_target     = 10
    scale_in_cooldown  = 120
    scale_out_cooldown = 30
  }

  validation {
    condition = (
      !var.scaling_config.enabled ||
      var.enable_queue_mode
    )
    error_message = "scaling_config.enabled requires enable_queue_mode = true."
  }
}
