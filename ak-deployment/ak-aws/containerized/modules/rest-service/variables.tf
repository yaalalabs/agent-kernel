variable "product_alias" {
  type        = string
  description = "Product alias for resource naming"
}

variable "env_alias" {
  type        = string
  description = "Environment alias for resource naming"
}

variable "module_name" {
  type        = string
  description = "Module name for resource naming"

  validation {
    # + 6 accounts for the "-alb"/"-nlb" suffix and its 2 joining hyphens
    condition     = length(var.product_alias) + length(var.env_alias) + length(var.module_name) + 6 <= 32
    error_message = "product_alias + env_alias + module_name must be at most 26 characters combined, so that the \"${var.product_alias}-${var.env_alias}-${var.module_name}-alb\"/\"-nlb\" load balancer name stays within AWS's 32-character limit."
  }
}

variable "region" {
  type        = string
  description = "AWS region"
}

variable "prefix" {
  type        = string
  description = "Resource name prefix"
}

variable "vpc_id" {
  type        = string
  description = "VPC ID"
}

variable "vpc_cidr" {
  type        = string
  description = "VPC CIDR block"
}

variable "subnet_ids" {
  type        = list(string)
  description = "Private subnet IDs for ECS tasks"
}

variable "ecs_cluster_arn" {
  type        = string
  description = "ECS cluster ARN"
}

variable "service_name" {
  type        = string
  description = "ECS service name"
}

variable "container_name" {
  type        = string
  description = "Container name"
}

variable "redis_url" {
  type        = string
  description = "Redis URL for session storage"
  default     = null
}

variable "valkey_url" {
  type        = string
  description = "Valkey URL for session storage"
  default     = null
}

variable "create_dynamodb_memory_table" {
  type        = bool
  description = "Whether DynamoDB memory table is created"
  default     = false
}

variable "dynamodb_memory_table_arn" {
  type        = string
  description = "DynamoDB memory table ARN"
  default     = null
}

variable "dynamodb_memory_table_name" {
  type        = string
  description = "DynamoDB memory table name"
  default     = null
}

variable "rest_service" {
  description = "REST service configuration object"
  type = object({
    cpu                               = optional(number, 256)
    memory                            = optional(number, 512)
    desired_count                     = optional(number, 1)
    container_port                    = optional(number, 8000)
    health_check_endpoint             = optional(string, "/health")
    health_check_grace_period_seconds = optional(number, 120)
    image_uri                         = string
    command                           = optional(list(string), null)
    environment_variables             = optional(map(string), {})
  })
}

variable "queue_mode" {
  type        = bool
  description = "Whether queue mode is enabled"
  default     = false
}

variable "input_queue_url" {
  type        = string
  description = "Input queue URL (for queue mode)"
  default     = null
}

variable "output_queue_url" {
  type        = string
  description = "Output queue URL (for queue mode)"
  default     = null
}

variable "response_store_table_name" {
  type        = string
  description = "Response store DynamoDB table name (for queue mode)"
  default     = null
}

variable "queue_config" {
  description = "Queue configuration for SQS batch size (for queue mode)"
  type = object({
    batch_size = number
  })
}

# WebSocket mode (async / stream)

variable "execution_mode" {
  type        = string
  description = "Execution mode (rest_sync, rest_async, async, stream)"
  default     = "rest_sync"
}

variable "websocket_mode" {
  type        = bool
  description = "Whether a WebSocket execution mode (async/stream) is enabled"
  default     = false
}

variable "websocket_connections_table_name" {
  type        = string
  description = "DynamoDB WebSocket connections table name (for WebSocket mode)"
  default     = null
}

variable "websocket_connections_table_arn" {
  type        = string
  description = "DynamoDB WebSocket connections table ARN (for WebSocket mode)"
  default     = null
}

variable "websocket_api_execution_arn" {
  type        = string
  description = "WebSocket API execution ARN (for ManageConnections permission)"
  default     = null
}

variable "websocket_endpoint_url" {
  type        = string
  description = "WebSocket API management endpoint URL for PostToConnection (https://{api-id}.execute-api.{region}.amazonaws.com/{stage})"
  default     = null
}

variable "tags" {
  type        = map(string)
  description = "Resource tags"
  default     = {}
}
