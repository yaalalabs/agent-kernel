variable "project_id" {
  type        = string
  description = "GCP project ID"
}

variable "region" {
  type        = string
  description = "GCP region"
}

variable "prefix" {
  type        = string
  description = "Prefix applied to every resource name (e.g. \"myproduct-dev-agents\")"

  validation {
    condition     = var.prefix != ""
    error_message = "prefix must be set to a non-empty value."
  }
}

variable "product_display_name" {
  type        = string
  description = "Product display name"
  default     = "An Agent Kernel deployment"
}

variable "is_production" {
  type        = bool
  description = "Is production"
  default     = false
}

# Docker image source — path to the dist/ directory containing Dockerfile + app files.
# The module builds and pushes the Docker image to Artifact Registry, then deploys
# it to Cloud Run with min_instance_count = 0 (scale-to-zero / serverless behaviour).
# This is the GCP equivalent of AWS Lambda Image type deployment.
variable "package_path" {
  type        = string
  description = "Path to the Docker build context (dist/ directory with Dockerfile)"
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

# Serverless: scale to zero by default (cold starts on first request).
# Increase min_instance_count to keep instances warm and eliminate cold starts.
variable "timeout" {
  type        = number
  description = "Maximum request timeout in seconds for Cloud Run (max 3600)"
  default     = 30
}

variable "backend_deadline" {
  type        = number
  description = "API Gateway backend deadline in seconds. Must be <= Cloud Run timeout."
  default     = 30
}

variable "min_instance_count" {
  type        = number
  description = "Minimum number of instances (0 = scale to zero / serverless)"
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

# CIDR block for the VPC Access Connector. Must not overlap existing subnets.
# If null, a unique CIDR is automatically computed based on deployment ID.
# This CIDR must also be allowed by VPC firewall rules (created automatically).
variable "connector_cidr" {
  type        = string
  description = "CIDR block for the VPC Access Connector. If null, auto-computed to avoid conflicts (e.g. '10.8.1.0/28')"
  default     = null
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
  description = "Create a Memorystore Redis instance for agent memory. Queue mode always creates it, as its response store"
  default     = false
}

variable "create_firestore_database" {
  type        = bool
  description = "Create a Firestore database for agent session storage"
  default     = false
}

variable "create_firestore_thread_collection" {
  type        = bool
  description = "Wire the Firestore-backed conversation thread store. Requires create_firestore_database; the collection itself is created implicitly on first write, so no extra Firestore resource is provisioned."
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
          ["GET", "POST", "PUT", "DELETE", "PATCH", "ANY"],
          upper(ep.method)
        )
      )
    ])
    error_message = "Each endpoint must have non-empty path, method, and overwrite_path. Method must be GET, POST, PUT, DELETE, PATCH, or ANY."
  }
}

variable "enable_mcp_server" {
  type        = bool
  description = "Enable MCP server and expose /mcp API endpoint"
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
# Both values must be provided to enable throttling (set null to disable).
variable "log_retention_days" {
  type        = number
  description = "Log retention in days for Cloud Logging. If set, updates the project default log bucket retention."
  default     = null
}

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

# JWT Authorizer — GCP equivalent of AWS API Gateway Lambda Authorizer.
# When set, API Gateway validates the JWT token in every request against the
# provided JWKS endpoint before forwarding to the Cloud Run service.
variable "allow_unauthenticated_invocation" {
  type        = bool
  description = "Allow unauthenticated direct invocation of the Cloud Run service URL. Set to false for stricter isolation (grant invoker only to specific principals)."
  default     = true
}

variable "authorizer" {
  description = "JWT authorizer configuration for API Gateway. When set, all endpoints require a valid JWT."
  type = object({
    issuer    = string       # JWT issuer URL
    jwks_uri  = string       # JWKS endpoint URL for public key verification
    audiences = list(string) # Expected JWT audience values
  })
  default = null
}

# -- Queue mode ------------------------------------------------------------------------------------

variable "queue_mode" {
  type        = bool
  description = "Split the deployment into an edge service (REST + response handler) and an agent-runner service that Pub/Sub pushes each request to, with a Memorystore response store (created automatically). The default. The app's config.yaml declares execution.queues.type: pubsub and execution.response_store.type: redis, and the runner needs agent_runner.command or its own image. Set false for the single-service deployment, where the agents run inside the service"
  default     = true
}

variable "execution_mode" {
  type        = string
  description = "Invocation mode in queue mode (AK_EXECUTION__MODE): rest_sync (wait for the reply) or rest_async (submit, then poll GET on the chat endpoint)"
  default     = "rest_sync"

  validation {
    condition     = contains(["rest_sync", "rest_async"], var.execution_mode)
    error_message = "execution_mode must be rest_sync or rest_async: async (WebSocket) and realtime replies are pushed to one instance, and Cloud Run instances are not individually addressable."
  }
}

variable "message_type" {
  type        = string
  description = "Reply delivery in queue mode (AK_EXECUTION__MESSAGE_TYPE): complete, or delta for SSE under rest_sync. null leaves the app's own setting"
  default     = null

  validation {
    condition     = var.message_type == null ? true : contains(["complete", "delta"], var.message_type)
    error_message = "message_type must be complete or delta."
  }
}

variable "queue_config" {
  type = object({
    input_queue_max_receive_count  = optional(number, 3)
    output_queue_max_receive_count = optional(number, 3)
    batch_size                     = optional(number, 1)
  })
  description = "Queue tuning in queue mode. A max_receive_count counts deliveries: the app permanently fails a message on that delivery, and the Pub/Sub dead-letter policy is the backstop. batch_size is messages per pull"
  default     = {}

  validation {
    condition     = var.queue_config.input_queue_max_receive_count >= 1 && var.queue_config.output_queue_max_receive_count >= 1
    error_message = "queue_config max_receive_count values must be at least 1."
  }

  validation {
    condition     = var.queue_config.batch_size >= 1 && var.queue_config.batch_size <= 1000
    error_message = "queue_config.batch_size must be between 1 and 1000 (Pub/Sub's pull maximum)."
  }
}

variable "agent_runner" {
  type = object({
    cpu                   = optional(string, "1")
    memory                = optional(string, "512Mi")
    min_instance_count    = optional(number, 0)
    max_instance_count    = optional(number, 10)
    concurrency           = optional(number, 5)
    package_path          = optional(string)
    image_uri             = optional(string)
    command               = optional(list(string))
    args                  = optional(list(string))
    environment_variables = optional(map(string), {})
  })
  description = "The agent-runner service in queue mode: Pub/Sub pushes each request to it, and Cloud Run scales it on those pushes between min_instance_count (0 scales to zero) and max_instance_count, each instance running up to concurrency agent runs. Its image is built from package_path, else image_uri, else the edge's image, which then needs its own command (e.g. [\"python\", \"-c\", \"from app import runner; runner()\"], where runner() calls CloudRunAgentRunner.run())"
  default     = {}

  validation {
    condition     = !var.queue_mode || var.agent_runner.package_path != null || var.agent_runner.image_uri != null || var.agent_runner.command != null
    error_message = "In queue mode the agent runner needs its own image (agent_runner.package_path or image_uri) or a command: on the edge's image without one it would run the edge's CMD and serve REST instead of the push route."
  }

  validation {
    condition     = var.agent_runner.min_instance_count >= 0 && var.agent_runner.min_instance_count <= var.agent_runner.max_instance_count && var.agent_runner.concurrency >= 1
    error_message = "agent_runner needs 0 <= min_instance_count <= max_instance_count and concurrency >= 1."
  }
}
