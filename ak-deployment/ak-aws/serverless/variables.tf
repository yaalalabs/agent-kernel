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
}

variable "is_production" {
  description = "Is production"
  type        = bool
  default     = false
}

variable "package_path" {
  type        = string
  description = "Zip package path or Docker image source path"
}
variable "scalable_mode" {
  type        = bool
  description = "When true, response_handler lambda will be created along with the response "
  default     = true
}

variable "execution_mode" {
  type        = string
  description = "Execution mode for the deployment. Required when scalable_mode is true, must be null when scalable_mode is false."
  default     = null
  validation {
    condition = var.execution_mode == null ? true : contains(["rest_sync", "rest_async", "ses_stream", "async"], var.execution_mode)
    error_message = "execution_mode must be one of: rest_sync, rest_async, ses_stream, async, or null."
  }
  validation {
    condition = !var.scalable_mode || var.execution_mode != null
    error_message = "execution_mode cannot be null when scalable_mode is true."
  }
  validation {
    condition = var.scalable_mode || var.execution_mode == null
    error_message = "execution_mode must be null when scalable_mode is false."
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
  default     = 30
}

variable "memory_size" {
  description = "Lambda memory size"
  type        = number
  default     = 128
}

variable "function_name" {
  description = "Lambda function name"
  type        = string
}

variable "function_description" {
  description = "Lambda function description"
  type        = string
}

variable "handler_path" {
  description = "Lambda handler path"
  type        = string
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
        length(trimspace(ep.path)) > 0 &&
        contains(
          ["GET", "POST", "PUT", "DELETE", "PATCH", "ANY", "$default"],
          upper(ep.method)
        )
      )
    ])
    error_message = "Each gateway_endpoints entry must: have a non-empty 'path', use a valid HTTP method: GET, POST, PUT, DELETE, PATCH, ANY, $default"
  }
}

variable "authorizer_function_name" {
  type        = string
  description = "Authorizer Lambda function name"
  default     = null
}

variable "authorizer_function_description" {
  type        = string
  description = "Authorizer Lambda function description"
  default     = "API Gateway Lambda Authorizer"
}

variable "authorizer_handler_path" {
  type        = string
  description = "Lambda authorizer handler path"
  default     = null
}

variable "authorizer_package_path" {
  type        = string
  description = "Authorizer Lambda package path or Docker image source path"
  default     = null
}

variable "authorizer_package_type" {
  type        = string
  description = "Authorizer Lambda deployment type Image/LocalZip/S3Zip"
  default     = null
}

variable "authorizer_module_name" {
  type        = string
  description = "Authorizer module name"
  default     = null
}

variable "authorizer_environment_variables" {
  description = "Authorizer Lambda environment variables"
  type        = map(string)
  default     = {}
}

variable "authorizer_result_ttl_in_seconds" {
  type        = number
  description = "Authorizer result TTL in seconds"
  default     = 150
}

variable "authorizer" {
  description = "Authorizer configuration object"
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
}


data "aws_ecr_authorization_token" "token" {}
data "aws_caller_identity" "current" {}

variable "response_handler" {
  description = "Response handler configuration object"
  type = object({
    function_name         = optional(string, "response-handler")
    timeout               = optional(number, 60)
    memory_size           = optional(number, 256)
    handler_path          = optional(string, "response_handler.handler")
    layers                = optional(list(string), [])
    environment_variables = optional(map(string), {})
  })
  default = {}
}

variable "agent_runner" {
  description = "Agent runner configuration object"
  type = object({
    function_name         = optional(string, "agent-runner")
    timeout               = optional(number, 300)
    memory_size           = optional(number, 512)
    handler_path          = optional(string, "agent_runner.handler")
    package_path          = optional(string, null)
    package_type          = optional(string, "LocalZip")
    layers                = optional(list(string), [])
    environment_variables = optional(map(string), {})
  })
  default = {}
}

variable "queue_config" {
  description = "SQS queues configuration object"
  type = object({
    # Queue names
    input_queue_name                = optional(string, null)
    output_queue_name               = optional(string, null)
    
    # Input queue configuration
    input_queue_visibility_timeout  = optional(number, null)
    input_queue_max_receive_count   = optional(number, null)
    input_queue_message_retention_seconds = optional(number, null)
    input_queue_max_message_size    = optional(number, null)
    input_queue_receive_wait_time_seconds = optional(number, null)
    input_queue_delay_seconds       = optional(number, null)
    input_queue_create_dlq          = optional(bool, null)
    input_queue_dlq_message_retention_seconds = optional(number, null)
    
    # Output queue configuration
    output_queue_visibility_timeout = optional(number, null)
    output_queue_max_receive_count  = optional(number, null)
    output_queue_message_retention_seconds = optional(number, null)
    output_queue_max_message_size   = optional(number, null)
    output_queue_receive_wait_time_seconds = optional(number, null)
    output_queue_delay_seconds      = optional(number, null)
    output_queue_create_dlq         = optional(bool, null)
    output_queue_dlq_message_retention_seconds = optional(number, null)
    
    # Common queue configuration
    fifo_queue                      = optional(bool, null)
    sqs_managed_sse_enabled         = optional(bool, null)
    kms_master_key_id               = optional(string, null)
    kms_data_key_reuse_period_seconds = optional(number, null)
    
    # FIFO-specific configuration (only used when fifo_queue = true)
    content_based_deduplication     = optional(bool, null)
    fifo_throughput_limit           = optional(string, null)
    deduplication_scope             = optional(string, null)
    
    # Access control
    enable_producer_access          = optional(bool, null)
    producer_arns                   = optional(list(string), null)
    enable_consumer_access          = optional(bool, null)
    consumer_role_arns              = optional(list(string), null)
    
    # Lambda event source mapping configuration
    batch_size                      = optional(number, 10)
    maximum_batching_window_in_seconds = optional(number, 5)
  })
  default = null
}


variable "response_store" {
  description = "Response store configuration object"
  type = object({
    suffix = optional(string, null)
    redis = optional(object({
      prefix = optional(string, "ak:response_messages:")
      url    = optional(string, null)
      ttl    = number
    }), null)
    dynamodb = optional(object({
      table_name = optional(string, "ak-responses")
      table_arn = optional(string, null)
      ttl        = number
    }), null)
  })
  default = null
  validation {
    condition = (var.execution_mode == null || var.execution_mode == "async") ? var.response_store == null : true
    error_message = "response_store must be null when execution_mode is null or 'async'."
  }
  validation {
    condition = (var.execution_mode != null && var.execution_mode != "async") ? var.response_store != null : true
    error_message = "response_store cannot be null when execution_mode is not null and not 'async'."
  }
  validation {
    condition = var.response_store == null ? true : (
      (var.response_store.redis != null && var.response_store.dynamodb == null) ||
      (var.response_store.dynamodb != null && var.response_store.redis == null)
    )
    error_message = "Exactly one of redis or dynamodb must be configured when response_store is provided."
  }
}
