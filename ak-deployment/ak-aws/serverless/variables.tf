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

variable "private_subnet_cidrs" {
  type = list(string)
  description = "CIDR blocks for the private subnets"
  default = ["10.0.3.0/24", "10.0.4.0/24"]
}

variable "gateway_endpoints" {
  description = "List of REST API endpoints to expose. If empty, a default POST /api/{api_version}/{agent_endpoint} is created."
  type = list(object({
    path = string        # e.g. "chat"
    method = string        # e.g. "GET", "POST", "PUT", "DELETE", "ANY"
  }))
  default = []
  validation {
    condition = alltrue([
      for ep in var.gateway_endpoints : (
        length(trimspace(ep.path)) > 0 &&
        length(trimspace(ep.method)) > 0 &&
        contains(["GET", "POST", "PUT", "DELETE", "PATCH", "ANY", "$default"], upper(ep.method))
      )
    ])
    error_message = "Each gateway_endpoints object must have non-empty 'path' and 'method' fields, and 'method' must be one of: GET, POST, PUT, DELETE, PATCH, ANY, $default."
  }
}

data "aws_ecr_authorization_token" "token" {}
data "aws_caller_identity" "current" {}
