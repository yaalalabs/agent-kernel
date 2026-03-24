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

variable "create_redis" {
  type        = bool
  description = "Whether to create Redis cluster"
  default     = false
}

variable "create_dynamodb" {
  type        = bool
  description = "Whether to create DynamoDB table"
  default     = false
}

variable "dynamodb_table_name" {
  type        = string
  description = "Name for the DynamoDB table"
  default     = "ak-responses"
}

variable "vpc_id" {
  type        = string
  description = "VPC ID for Redis cluster"
  default     = null
}

variable "vpc_cidr" {
  type        = string
  description = "VPC CIDR for Redis cluster"
  default     = null
}

variable "subnet_ids" {
  type        = list(string)
  description = "Subnet IDs for Redis cluster"
  default     = []
}

variable "response_store_suffix" {
  type        = string
  description = "Suffix for response store module naming"
  default     = null
}