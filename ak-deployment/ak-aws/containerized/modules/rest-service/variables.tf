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
    cpu                   = optional(number, 256)
    memory                = optional(number, 512)
    desired_count         = optional(number, 1)
    container_port        = optional(number, 8000)
    health_check_endpoint = optional(string, "/health")
    image_uri             = string
    command               = optional(list(string), null)
    environment_variables = optional(map(string), {})
  })
}

variable "enable_queue_mode" {
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

variable "tags" {
  type        = map(string)
  description = "Resource tags"
  default     = {}
}
