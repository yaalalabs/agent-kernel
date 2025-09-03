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

variable "redis_host" {
  type        = string
  description = "Redis host. If not provided new redis cluster will be created"
  default     = null
}

variable "redis_port" {
  type        = number
  description = "Redis port should be provided along with the redis host"
  default     = 6379
}

variable "ecs_cpu" {
  type        = number
  description = "Fargate CPU units"
  default     = 256
}

variable "ecs_memory" {
  type        = number
  description = "Fargate memory in MiB"
  default     = 512
}

variable "ecs_desired_count" {
  type        = number
  description = "Desired count for ECS service"
  default     = 1
}

variable "ecs_container_port" {
  type        = number
  description = "Container port exposed by the ECS service"
  default     = 8000
}

variable "ecs_health_check_path" {
  type        = string
  description = "Health check path for ALB target group"
  default     = "/health"
}

variable "container_type" {
  type        = string
  description = "Container type (ECS or EKS)"
  default     = "ecs"
  validation {
    condition = contains(["ecs", "eks"], lower(var.container_type))
    error_message = "Container type must be either 'efs' or 'eks'."
  }
}

data "aws_ecr_authorization_token" "token" {}
data "aws_caller_identity" "current" {}