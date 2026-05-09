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

variable "module_type" {
  type        = string
  description = "Module type"
  default     = "python"
}

variable "module_name" {
  type        = string
  description = "Module name"
  default     = ""
  validation {
    condition     = !var.enable_api_gateway || var.module_name != ""
    error_message = "module_name must be set to a non-empty value when enable_api_gateway is true."
  }
}

variable "is_production" {
  description = "Is production"
  type        = bool
  default     = false
}

variable "cloudwatch_logs_retention_in_days" {
  type        = number
  description = "CloudWatch log retention period in days for the request handler Lambda"
  default     = 90
}
variable "queue_mode" {
  type        = bool
  description = "When true, response_handler lambda will be created along with the response "
  default     = false
}

variable "enable_api_gateway" {
  type        = bool
  description = "When false, the request handler, API Gateway, and authorizer are not created. Only allowed when queue_mode is true."
  default     = true
  validation {
    condition     = var.enable_api_gateway || var.queue_mode
    error_message = "enable_api_gateway can only be false when queue_mode is true."
  }
}

variable "execution_mode" {
  type        = string
  description = "Execution mode for the deployment. Allowed values: rest_sync, async (always allowed), rest_async and other modes (only when queue_mode is true)."
  default     = "rest_sync"
  validation {
    condition = contains(["rest_sync", "rest_async", "async"], var.execution_mode)
    error_message = "execution_mode must be one of: rest_sync, rest_async, async."
  }
  validation {
    condition = var.queue_mode || contains(["rest_sync", "async"], var.execution_mode)
    error_message = "execution_mode must be rest_sync or async when queue_mode is false."
  }
}

variable "event_source_mapping" {
  description = "Event source mapping"
  type        = any
  default = []
}

variable "environment_variables" {
  description = "Environment variables"
  type        = any
  default = {}
}

variable "timeout" {
  description = "Lambda timeout"
  type        = number
  default     = 45
}

variable "memory_size" {
  description = "Lambda memory size"
  type        = number
  default     = 128
}

variable "function_name" {
  description = "Lambda function name"
  type        = string
  default     = ""
  validation {
    condition     = !var.enable_api_gateway || var.function_name != ""
    error_message = "function_name must be set to a non-empty value when enable_api_gateway is true."
  }
}

variable "function_description" {
  description = "Lambda function description"
  type        = string
  default     = ""
  validation {
    condition     = !var.enable_api_gateway || var.function_description != ""
    error_message = "function_description must be set to a non-empty value when enable_api_gateway is true."
  }
}

variable "handler_path" {
  description = "Lambda handler path"
  type        = string
  default     = ""
  validation {
    condition     = !var.enable_api_gateway || var.handler_path != ""
    error_message = "handler_path must be set to a non-empty value when enable_api_gateway is true."
  }
}

variable "package_path" {
  type        = string
  description = "Zip package path or Docker image source path"
  default     = ""
  validation {
    condition     = !var.enable_api_gateway || var.package_path != ""
    error_message = "package_path must be set to a non-empty value when enable_api_gateway is true."
  }
}

variable "package_type" {
  description = "Lambda deployment type Image/LocalZip/S3Zip"
  type        = string
  default     = "LocalZip"
}

variable "layers" {
  description = "Lambda layers"
  type = list(string)
  default = []
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
  description = "Create a redis cluster to store Agent memory"
  default     = false
}

variable "create_dynamodb_memory_table" {
  type        = bool
  description = "Create a dynamodb table to store the Agent memory"
  default     = false
}

variable "create_redis_response_store" {
  type        = bool
  description = "Create or reuse Redis for response storage"
  default     = false
  nullable    = false
}

variable "create_dynamodb_response_store" {
  type        = bool
  description = "Create a DynamoDB table for response storage"
  default     = false
  nullable    = false
  validation {
    condition     = !(var.create_redis_response_store && var.create_dynamodb_response_store)
    error_message = "create_redis_response_store and create_dynamodb_response_store cannot both be true."
  }
}

variable "create_dynamodb_multimodal_memory_table" {
  type        = bool
  description = "Create a dynamodb table to store the Agent multimodal memory"
  default     = false
}

variable "private_subnet_cidrs" {
  type = list(string)
  description = "CIDR blocks for the private subnets"
  default = ["10.0.3.0/24", "10.0.4.0/24"]
}

variable "api_version" {
  type        = string
  description = "API version"
  default     = "v1"
  validation {
    condition     = var.execution_mode == "async" || (var.api_version != null && length(trimspace(var.api_version)) > 0)
    error_message = "api_version must not be null, empty, or whitespace-only when execution_mode is not 'async'."
  }
}

variable "agent_endpoint" {
  type        = string
  description = "Agent invocation endpoint"
  default     = "chat"
  validation {
    condition     = var.execution_mode == "async" || (var.agent_endpoint != null && length(trimspace(var.agent_endpoint)) > 0)
    error_message = "agent_endpoint must not be null, empty, or whitespace-only when execution_mode is not 'async'."
  }
}

variable "api_base_path" {
  type        = string
  description = "Optional base path segment for the API (e.g., 'api'). Set to null or empty to omit."
  default     = "api"
  validation {
    condition     = var.execution_mode == "async" || (var.agent_endpoint != null && length(trimspace(var.agent_endpoint)) > 0)
    error_message = "api_base_path must not be whitespace-only when provided and execution_mode is not 'async'. Use null or empty string to omit."
  }
}

variable "ws_chat_route" {
  type        = string
  description = "WebSocket chat route"
  default     = "chat"

  validation {
    condition     = var.execution_mode != "async" || (var.ws_chat_route != null && length(trimspace(var.ws_chat_route)) > 0)
    error_message = "ws_chat_route must not be null, empty, or whitespace-only."
  }

  validation {
    condition     = var.execution_mode != "async" || (var.ws_chat_route != null && can(regex("^[a-zA-Z0-9_-]+$", var.ws_chat_route)))
    error_message = "ws_chat_route must not be null and must contain only alphanumeric characters, hyphens (-), and underscores (_). Note: '$' prefix is reserved for predefined routes."
  }
}

variable "ws_routes" {
  type = list(object({
    route = string
  }))
  description = "List of custom WebSocket routes to add. Each object should have a 'route' key with the custom route name."
  default     = []

  validation {
    condition     = var.execution_mode == "async" || length(var.ws_routes) == 0
    error_message = "'ws_routes' can only be defined in 'async' (websocket) execution mode."
  }

  validation {
    condition     = var.execution_mode != "async" || alltrue([for r in var.ws_routes : r.route != null && length(trimspace(r.route)) > 0])
    error_message = "Routes in 'ws_routes' must not be null, empty, or whitespace-only."
  }

  validation {
    condition     = var.execution_mode != "async" || alltrue([for r in var.ws_routes : r.route != null && can(regex("^[a-zA-Z0-9_-]+$", r.route))])
    error_message = "Routes in 'ws_routes' must not be null and must contain only alphanumeric characters, hyphens (-), and underscores (_). Note: '$' prefix is reserved for predefined routes."
  }
}

variable "gateway_endpoints" {
  description = "List of REST API endpoints to expose. If empty, a default POST /api/{api_version}/{agent_endpoint} is created."

  type = list(object({
    path   = string   # e.g. "/app/check", "/health", "/app/status/test"
    method = string   # GET, POST, PUT, DELETE, ANY
  }))

  default = []

  validation {
    condition = alltrue([
      for ep in var.gateway_endpoints : (
        ep.path != null && length(trimspace(ep.path)) > 0 &&
        ep.method != null && contains(
          ["GET", "POST", "PUT", "DELETE", "PATCH", "ANY", "$default"],
          upper(ep.method)
        )
      )
    ])

    error_message = "Each gateway_endpoints entry must: have a non-null, non-empty 'path', and a non-null valid HTTP method: GET, POST, PUT, DELETE, PATCH, ANY, $default"
  }

  validation {
    condition     = var.execution_mode != "async" || length(var.gateway_endpoints) == 0
    error_message = "'gateway_endpoints' cannot be defined in 'async' (websocket) execution mode."
  }
}

variable "authorizer" {
  description = "Authorizer configuration object. Optional when execution_mode is 'rest_sync' or 'rest_async', must be null when execution_mode is 'async'."
  type = object({
    description           = optional(string, "API Gateway Lambda Authorizer")
    function_name         = string
    handler_path          = string
    package_path          = string
    package_type          = string
    module_name           = string
    result_ttl_in_seconds = optional(number, 150)
    environment_variables = optional(map(string), {})
  })
  default = null
  validation {
    condition     = !(var.execution_mode == "async" && var.authorizer != null)
    error_message = "'authorizer' cannot be defined in 'async' (websocket) execution mode."
  }
}

variable "ws_connection_handler" {
  description = "WebSocket connection handler configuration object. Required when execution_mode is 'async', must be empty ({}) or null when execution_mode is 'rest_sync' or 'rest_async'. Only supports LocalZip package type."
  type = object({
    function_name         = optional(string, "ws-connection-handler")
    function_description  = optional(string, "WebSocket connection handler Lambda for $connect and $disconnect routes")
    timeout               = optional(number, 30)
    memory_size           = optional(number, 256)
    handler_path          = optional(string, "ws_connection_handler.handler")
    module_name           = optional(string, "ws-connection-handler")
    package_path          = optional(string, null)
    layers                = optional(list(string), [])
    cloudwatch_logs_retention_in_days = optional(number, 90)
    environment_variables = optional(map(string), {})
  })
  default = {}
  validation {
    condition     = var.execution_mode != "async" || try(var.ws_connection_handler.package_path, null) != null
    error_message = "ws_connection_handler.package_path is required when execution_mode is 'async'."
  }
}

variable "response_handler" {
  description = "Response handler configuration object"
  type = object({
    function_name         = optional(string, "response-handler")
    function_description   = optional(string, "Response handler Lambda for processing SQS messages and storing responses")
    timeout               = optional(number, 45)
    memory_size           = optional(number, 256)
    handler_path          = optional(string, "response_handler.handler")
    module_name           = optional(string, "response-handler")
    package_path          = optional(string, null)
    package_type          = optional(string, "LocalZip")
    layers                = optional(list(string), [])
    cloudwatch_logs_retention_in_days = optional(number, 90)
    environment_variables = optional(map(string), {})
  })
  default = {}
  validation {
    condition     = !var.queue_mode || try(var.response_handler.package_path, null) != null
    error_message = "response_handler.package_path must be set when queue_mode is true."
  }
}

variable "agent_runner" {
  description = "Agent runner configuration object"
  type = object({
    function_name         = optional(string, "agent-runner")
    function_description   = optional(string, "Agent runner Lambda for processing input queue messages")
    timeout               = optional(number, 45)
    memory_size           = optional(number, 512)
    handler_path          = optional(string, "agent_runner.handler")
    module_name           = optional(string, "agent-runner")
    package_path          = optional(string, null)
    package_type          = optional(string, "LocalZip")
    layers                = optional(list(string), [])
    cloudwatch_logs_retention_in_days = optional(number, 90)
    environment_variables = optional(map(string), {})
  })
  default = {}
  validation {
    condition     = !var.queue_mode || try(var.agent_runner.package_path, null) != null
    error_message = "agent_runner.package_path must be set when queue_mode is true."
  }
}

variable "queue_config" {
  description = "SQS queues configuration object. When omitted, the object defaults are used."
  type = object({
    # Queue names
    input_queue_name  = optional(string, "input-queue")
    output_queue_name = optional(string, "output-queue")

    # Input queue configuration
    input_queue_visibility_timeout            = optional(number, 60)
    input_queue_max_receive_count             = optional(number, 3)
    input_queue_message_retention_seconds     = optional(number, 300)
    input_queue_max_message_size              = optional(number, 262144)
    input_queue_receive_wait_time_seconds     = optional(number, 0)
    input_queue_delay_seconds                 = optional(number, 0)
    input_queue_create_dlq                    = optional(bool, false)
    input_queue_dlq_message_retention_seconds = optional(number, 300)

    # Output queue configuration
    output_queue_visibility_timeout            = optional(number, 60)
    output_queue_max_receive_count             = optional(number, 3)
    output_queue_message_retention_seconds     = optional(number, 300)
    output_queue_max_message_size              = optional(number, 262144)
    output_queue_receive_wait_time_seconds     = optional(number, 0)
    output_queue_delay_seconds                 = optional(number, 0)
    output_queue_create_dlq                    = optional(bool, false)
    output_queue_dlq_message_retention_seconds = optional(number, 300)

    # Common queue configuration
    fifo_queue                        = optional(bool, true)
    sqs_managed_sse_enabled           = optional(bool, true)
    kms_master_key_id                 = optional(string, null)
    kms_data_key_reuse_period_seconds = optional(number, null)

    # FIFO-specific configuration (only used when fifo_queue = true)
    content_based_deduplication = optional(bool, false)
    fifo_throughput_limit       = optional(string, "perMessageGroupId")
    deduplication_scope         = optional(string, "messageGroup")

    # Access control
    enable_producer_access = optional(bool, true)
    producer_arns          = optional(list(string), [])
    enable_consumer_access = optional(bool, true)
    consumer_role_arns     = optional(list(string), [])

    # Lambda event source mapping configuration
    batch_size                         = optional(number, 10)
    maximum_batching_window_in_seconds = optional(number, 0) # The maximum time (in seconds) Lambda will wait to gather messages into a batch before triggering the Lambda function
  })
  default = {}
  validation {
    condition     = !var.queue_mode || var.queue_config != null
    error_message = "queue_config must NOT be null when queue_mode is true. You may leave it without defining (it will use the default) or define the object's parameters, but it cannot be null."
  }
}
