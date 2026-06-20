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

variable "subnet_ids" {
  type        = list(string)
  description = "Private subnet IDs for ECS tasks"
}

variable "ecs_cluster_arn" {
  type        = string
  description = "ECS cluster ARN"
}

variable "ecs_cluster_name" {
  type        = string
  description = "ECS cluster name"
}

variable "input_queue_url" {
  type        = string
  description = "Input queue URL"
}

variable "input_queue_arn" {
  type        = string
  description = "Input queue ARN"
}

variable "output_queue_url" {
  type        = string
  description = "Output queue URL"
}

variable "output_queue_arn" {
  type        = string
  description = "Output queue ARN"
}

variable "redis_url" {
  type        = string
  description = "Redis URL for session storage"
  default     = null
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

variable "agent_runner" {
  description = "Agent runner configuration object"
  type = object({
    cpu                = optional(number, 512)
    memory             = optional(number, 1024)
    desired_count      = optional(number, 1)
    image_uri          = optional(string, null)
    command            = optional(list(string), null)
    environment_variables = optional(map(string), {})
  })
}

variable "queue_config" {
  description = "Queue configuration for input max_receive_count"
  type = object({
    input_queue_max_receive_count = number
  })
}

variable "scaling_config" {
  description = "Auto scaling configuration object"
  type = object({
    enabled                = optional(bool, false)
    min_count              = optional(number, 0)
    max_count              = optional(number, 10)
    backlog_target         = optional(number, 10)
    scale_in_cooldown      = optional(number, 120)
    scale_out_cooldown     = optional(number, 30)
  })
  default = {
    enabled = false
  }
}

variable "default_image_uri" {
  type        = string
  description = "Default Docker image URI (from main service)"
}

variable "tags" {
  type        = map(string)
  description = "Resource tags"
  default     = {}
}

variable "account_id" {
  type        = string
  description = "AWS Account ID"
}
